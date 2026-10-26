"""WhatsApp ativo somente durante o job, com sessão cifrada fora do runner."""
import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from cloud_run import configure


def send_test_once(config):
    from contextlib import closing
    from database.models import connect
    from services.cloud import CloudState
    from publishers.whatsapp import publish
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if not run_id.isdigit():
        raise ValueError("Teste exige um identificador de execução do GitHub")
    state = CloudState(config.database_path)
    state.restore()
    with closing(connect(config.database_path)) as db:
        db.execute("CREATE TABLE IF NOT EXISTS whatsapp_tests (run_id TEXT PRIMARY KEY,state TEXT NOT NULL)")
        existing = db.execute("SELECT run_id,state FROM whatsapp_tests WHERE state<>'superseded_unconfirmed' LIMIT 1").fetchone()
        if existing:
            if existing[1] != 'confirmed':
                from publishers.whatsapp import bridge_token
                request = Request('http://127.0.0.1:8787/test-status',headers={'Authorization':'Bearer '+bridge_token()})
                for attempt in range(13):
                    with urlopen(request,timeout=60) as response: result = json.load(response)
                    if result.get('confirmed') or not result.get('found') or attempt==12:
                        break
                    time.sleep(5)
                if result.get('confirmed') and result.get('message_id'):
                    db.execute("UPDATE whatsapp_tests SET state='confirmed' WHERE run_id=?",(existing[0],))
                    db.commit()
                    state.checkpoint(db)
                    print('Teste anterior encontrado com confirmação; nenhuma nova mensagem enviada.',flush=True)
                else:
                    print('Teste anterior: encontrado=' + str(bool(result.get('found'))) + '; confirmação=' + str(bool(result.get('confirmed'))) + '; acks=' + str(result.get('acks')),flush=True)
                    raise RuntimeError('Teste anterior sem confirmação; não reenviado automaticamente')
            print("Teste de instalação já reservado; não repetir envio em outro job.",flush=True)
            return
        db.execute("INSERT INTO whatsapp_tests VALUES (?, 'sending')", (run_id,))
        db.commit()
        state.checkpoint(db)
        from pathlib import Path
        settings = json.loads(Path("settings.json").read_text(encoding="utf-8"))
        publish("Teste técnico do Promos Gamer pelo GitHub Actions. Não é uma oferta.", settings["whatsapp_group_id"])
        db.execute("UPDATE whatsapp_tests SET state='confirmed' WHERE run_id=?", (run_id,))
        db.commit()
        state.checkpoint(db)
        print("Mensagem única de teste confirmada pelo WhatsApp.",flush=True)


def send_preview_once(config):
    """Envia uma única prévia de preço real, sem alegar desconto histórico."""
    from contextlib import closing
    from pathlib import Path
    from collectors.registry import LazyBrowser, build_sources
    from database.models import connect
    from services.cloud import CloudState
    from services.niche import category_for
    from services.seller_trust import seller_rejection
    from publishers.whatsapp import publish

    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if not run_id.isdigit():
        raise ValueError("Prévia exige uma execução do GitHub")
    settings = json.loads(Path("settings.json").read_text(encoding="utf-8"))
    group = settings.get("whatsapp_group_id", "")
    if not group.endswith("@g.us"):
        raise ValueError("Configure o grupo antes da prévia")
    state = CloudState(config.database_path)
    state.restore()
    with closing(connect(config.database_path)) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS whatsapp_previews (
            preview_key TEXT PRIMARY KEY, state TEXT NOT NULL,
            run_id TEXT NOT NULL, message_id TEXT)""")
        existing = db.execute("SELECT state FROM whatsapp_previews WHERE preview_key='weekly-preview-1'").fetchone()
        if existing:
            print("Prévia já reservada; nenhuma mensagem repetida.", flush=True)
            return
        entries = json.loads(Path("products.json").read_text(encoding="utf-8"))
        entries = [entry for entry in entries if entry.get("store") == "kabum" and entry.get("enabled", True)]
        browser = LazyBrowser()
        try:
            source = build_sources(db, settings, browser)["kabum"]
            offer = None
            for entry in entries:
                try:
                    current = source.collect(entry)
                except Exception:
                    continue
                if (current.available and current.price_cents > 0 and current.payment_terms.strip()
                        and category_for(current.title) and not seller_rejection(current, config.trusted_sellers)):
                    offer = current
                    break
        finally:
            browser.close()
        if offer is None:
            raise RuntimeError("Nenhum produto KaBuM elegível para a prévia nesta consulta")
        title = " ".join(offer.title.split())[:180]
        terms = " ".join(offer.payment_terms.split())[:80]
        reais = f"{offer.price_cents // 100:,}".replace(",", ".")
        price = f"R$ {reais},{offer.price_cents % 100:02d}"
        message = ("🧪 PRÉVIA REAL — teste da automação\n"
                   "Este produto está disponível, mas ainda não teve desconto de 15% confirmado "
                   "pela comparação com os últimos 7 dias. Não é uma promoção aprovada.\n\n"
                   f"{title}\nPreço atual: {price} ({terms})\n"
                   "Vendido e entregue pela KaBuM. Frete não incluído.\n"
                   f"{offer.affiliate_url}")
        db.execute("INSERT INTO whatsapp_previews VALUES ('weekly-preview-1','sending',?,NULL)", (run_id,))
        db.commit()
        state.checkpoint(db)
        try:
            message_id = publish(message, group)
        except Exception:
            db.execute("UPDATE whatsapp_previews SET state='uncertain' WHERE preview_key='weekly-preview-1'")
            db.commit()
            state.checkpoint(db)
            raise
        db.execute("UPDATE whatsapp_previews SET state='confirmed', message_id=? WHERE preview_key='weekly-preview-1'",
                   (message_id,))
        db.commit()
        state.checkpoint(db)
        print("Prévia única de produto real confirmada pelo WhatsApp.", flush=True)


def run(connect_only=False, limit=20, send_test=False, send_preview=False):
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise ValueError("Este comando deve ser executado no GitHub Actions")
    if (send_test or send_preview) and not connect_only or (send_test and send_preview):
        raise ValueError("Envio de validação exige um único modo explícito de conexão")
    config = configure(limit)
    env = dict(os.environ, WHATSAPP_AUTH_MODE="supabase", WHATSAPP_ALLOW_QR=str(connect_only and not (send_test or send_preview)).lower(),
               WHATSAPP_BRIDGE_TOKEN=secrets.token_hex(32), WHATSAPP_RUNNER_BRIDGE="true")
    process = subprocess.Popen(["node", "publishers/whatsapp_bridge.cjs"], env=env)
    try:
        deadline = time.monotonic() + (600 if connect_only and not (send_test or send_preview) else 180 if (send_test or send_preview) else 300)
        next_report = 0
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Ponte encerrou; execute o workflow de conexão se a sessão expirou")
            try:
                request = Request("http://127.0.0.1:8787/health", headers={"Authorization":"Bearer " + env["WHATSAPP_BRIDGE_TOKEN"]})
                with urlopen(request, timeout=10) as response:
                    health = json.load(response)
                if health.get("ready") and health.get("session_saved") and health.get("group_found"):
                    break
            except HTTPError as error:
                if time.monotonic() >= next_report:
                    try:
                        status = json.load(error)
                        safe = {key:status.get(key) for key in ('ready','phase','connection_state','group_found','session_saved')}
                        print('Aguardando WhatsApp: ' + json.dumps(safe),flush=True)
                    except ValueError:
                        print('Aguardando WhatsApp: HTTP ' + str(error.code),flush=True)
                    next_report = time.monotonic() + 30
                error.close()
            except (URLError, TimeoutError, ValueError):
                pass
            time.sleep(3)
        else:
            raise RuntimeError("WhatsApp não ficou pronto no prazo; confira conexão e grupo")
        if connect_only:
            if send_test or send_preview:
                # O publicador deve usar a mesma ponte privada criada neste job.
                previous = {key:os.environ.get(key) for key in ("WHATSAPP_BRIDGE_TOKEN","WHATSAPP_RUNNER_BRIDGE")}
                try:
                    for key in previous: os.environ[key] = env[key]
                    if send_test:
                        send_test_once(config)
                    else:
                        send_preview_once(config)
                finally:
                    for key,value in previous.items():
                        if value is None: os.environ.pop(key,None)
                        else: os.environ[key] = value
            print("Sessão da nuvem conectada e persistida." + ("" if (send_test or send_preview) else " Nenhuma mensagem enviada."), flush=True)
            if send_test or send_preview:
                print("O envio solicitado de teste foi tratado separadamente; nenhuma oferta publicada.",flush=True)
            return
        subprocess.run([sys.executable,"cloud_run.py","--send","--limit",str(limit)],env=env,check=True)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise RuntimeError("Ponte não concluiu o salvamento final da sessão")
        if process.returncode not in (0, None):
            raise RuntimeError("Ponte encerrou com falha; confira os logs sem compartilhar credenciais")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connect", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--test", action="store_true", help="Enviar uma mensagem técnica explicitamente solicitada, sem repetir no mesmo run")
    parser.add_argument("--preview", action="store_true", help="Enviar uma única prévia real sem alegar promoção aprovada")
    args = parser.parse_args()
    run(args.connect, args.limit, args.test, args.preview)

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
        if db.execute("SELECT 1 FROM publications LIMIT 1").fetchone():
            print("Promoção real já publicada; prévia desnecessária.", flush=True)
            return
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
                   f"Este produto está disponível, mas ainda não teve desconto de {config.minimum_discount_percent:g}% confirmado "
                   f"pela comparação com os últimos {config.history_days} dias. Não é uma promoção aprovada.\n\n"
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


def send_media_test_once(config):
    """Único teste com foto explicitamente autorizado, separado das promoções."""
    from contextlib import closing
    from pathlib import Path
    from collectors.registry import LazyBrowser, build_sources
    from database.models import connect
    from services.cloud import CloudState
    from services.seller_trust import seller_rejection
    from publishers.whatsapp import publish

    run_id = os.environ.get('GITHUB_RUN_ID', '')
    if not run_id.isdigit():
        raise ValueError('Teste de mídia exige execução do GitHub.')
    settings = json.loads(Path('settings.json').read_text(encoding='utf-8'))
    state = CloudState(config.database_path)
    state.restore()
    with closing(connect(config.database_path)) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS whatsapp_media_tests (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), state TEXT NOT NULL,
            run_id TEXT NOT NULL, message_id TEXT, error_code TEXT)''')
        if 'error_code' not in {column[1] for column in db.execute('PRAGMA table_info(whatsapp_media_tests)')}:
            db.execute('ALTER TABLE whatsapp_media_tests ADD COLUMN error_code TEXT')
        if db.execute('SELECT 1 FROM whatsapp_media_tests').fetchone():
            print('Teste com foto já reservado; nenhuma repetição automática.', flush=True)
            return
        entries = json.loads(Path('products.json').read_text(encoding='utf-8'))
        browser = LazyBrowser()
        image_url = ''
        try:
            source = build_sources(db, settings, browser)['kabum']
            for entry in entries:
                if entry.get('store') != 'kabum' or not entry.get('enabled', True):
                    continue
                offer = source.collect(entry)
                if offer.available and offer.image_url and not seller_rejection(offer):
                    image_url = offer.image_url
                    break
        finally:
            browser.close()
        if not image_url:
            raise ValueError('Nenhuma foto de produto validado disponível para o teste.')
        db.execute("INSERT INTO whatsapp_media_tests(singleton,state,run_id,message_id) VALUES (1,'sending',?,NULL)", (run_id,))
        db.commit()
        state.checkpoint(db)
        try:
            message_id = publish('🧪 Teste técnico do Promos Gamer: validação de envio com foto pelo GitHub Actions. Não é uma promoção.',
                                 settings['whatsapp_group_id'], image_url=image_url, require_image=True)
        except Exception as error:
            code = getattr(error, 'code', '')
            if code not in ('whatsapp_send_failed', 'whatsapp_confirmation_missing',
                             'whatsapp_transport_unknown', 'whatsapp_bridge_http_error'):
                code = 'media_test_failed'
            db.execute("UPDATE whatsapp_media_tests SET state='uncertain',error_code=?", (code,))
            db.commit()
            state.checkpoint(db)
            raise
        db.execute("UPDATE whatsapp_media_tests SET state='confirmed',message_id=?,error_code=NULL", (message_id,))
        from datetime import datetime, timezone
        db.execute('''CREATE TABLE IF NOT EXISTS whatsapp_health (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), checked_at TEXT NOT NULL,
            ready INTEGER NOT NULL, group_found INTEGER NOT NULL, session_saved INTEGER NOT NULL)''')
        db.execute('INSERT OR REPLACE INTO whatsapp_health VALUES (1,?,1,1,1)',
                   (datetime.now(timezone.utc).isoformat(),))
        db.commit()
        state.checkpoint(db)
        print('Teste único com foto confirmado pelo servidor do WhatsApp.', flush=True)


def reconcile_media_test(config, token):
    """Só consulta a mensagem exata do teste; nunca chama /send."""
    from contextlib import closing
    from database.models import connect
    from services.cloud import CloudState
    state = CloudState(config.database_path)
    state.restore()
    with closing(connect(config.database_path)) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'whatsapp_media_tests' not in tables:
            return
        row = db.execute('SELECT state FROM whatsapp_media_tests WHERE singleton=1').fetchone()
        if not row or row[0] == 'confirmed':
            return
        request = Request('http://127.0.0.1:8787/media-test-status',
                          headers={'Authorization': 'Bearer ' + token})
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
        if result.get('confirmed') is True and isinstance(result.get('message_id'), str) and result['message_id']:
            db.execute("UPDATE whatsapp_media_tests SET state='confirmed',message_id=? WHERE singleton=1",
                       (result['message_id'],))
            db.commit()
            state.checkpoint(db)
            print('Teste com foto encontrado com ACK; nenhuma nova mensagem enviada.', flush=True)
        else:
            print('Reconciliação do teste com foto: encontrado=' + str(result.get('found') is True)
                  + '; confirmado=False; nenhuma nova mensagem enviada.', flush=True)


def run(connect_only=False, limit=20, send_test=False, send_preview=False, verify_only=False, send_media_test=False, reset_session=False):
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise ValueError("Este comando deve ser executado no GitHub Actions")
    if verify_only and (send_test or send_preview or send_media_test):
        raise ValueError('Verificação não permite envio de mensagens.')
    connect_only = connect_only or verify_only
    send_validation = send_test or send_preview or send_media_test
    if send_validation and not connect_only or sum(map(bool, (send_test, send_preview, send_media_test))) > 1:
        raise ValueError("Envio de validação exige um único modo explícito de conexão")
    config = configure(limit)
    if reset_session and (not connect_only or send_validation or verify_only):
        raise ValueError('Reset de sessão só pode ser usado na conexão sem envio.')
    env = dict(os.environ, WHATSAPP_AUTH_MODE="supabase", WHATSAPP_ALLOW_QR=str(connect_only and not (send_validation or verify_only)).lower(),
               WHATSAPP_RESET_SESSION=str(bool(reset_session)).lower(),
               WHATSAPP_BRIDGE_TOKEN=secrets.token_hex(32), WHATSAPP_RUNNER_BRIDGE="true")
    process = subprocess.Popen(["node", "publishers/whatsapp_bridge.cjs"], env=env)
    try:
        deadline = time.monotonic() + (300 if verify_only else 600 if connect_only and not send_validation else 180 if send_validation else 300)
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
            if verify_only:
                from contextlib import closing
                from datetime import datetime, timezone
                from database.models import connect
                from services.cloud import CloudState
                state = CloudState(config.database_path)
                state.restore()
                with closing(connect(config.database_path)) as db:
                    db.execute('''CREATE TABLE IF NOT EXISTS whatsapp_health (
                        singleton INTEGER PRIMARY KEY CHECK(singleton=1), checked_at TEXT NOT NULL,
                        ready INTEGER NOT NULL, group_found INTEGER NOT NULL, session_saved INTEGER NOT NULL)''')
                    db.execute('INSERT OR REPLACE INTO whatsapp_health VALUES (1,?,1,1,1)',
                               (datetime.now(timezone.utc).isoformat(),))
                    db.commit()
                    state.checkpoint(db)
                print('Conexão, grupo e sessão persistida verificados. Nenhuma mensagem enviada.', flush=True)
                reconcile_media_test(config, env['WHATSAPP_BRIDGE_TOKEN'])
                return
            if send_validation:
                # O publicador deve usar a mesma ponte privada criada neste job.
                previous = {key:os.environ.get(key) for key in ("WHATSAPP_BRIDGE_TOKEN","WHATSAPP_RUNNER_BRIDGE")}
                try:
                    for key in previous: os.environ[key] = env[key]
                    if send_test:
                        send_test_once(config)
                    elif send_media_test:
                        send_media_test_once(config)
                    else:
                        send_preview_once(config)
                finally:
                    for key,value in previous.items():
                        if value is None: os.environ.pop(key,None)
                        else: os.environ[key] = value
            print("Sessão da nuvem conectada e persistida." + ("" if send_validation else " Nenhuma mensagem enviada."), flush=True)
            if send_validation:
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
    parser.add_argument('--verify', action='store_true', help='Verifica sessão/grupo sem QR nem mensagens')
    parser.add_argument('--media-test', action='store_true', help='Teste único com foto explicitamente autorizado')
    parser.add_argument('--reset-session', action='store_true', help='Apaga a sessão remota e aguarda um novo QR; sem envio')
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--test", action="store_true", help="Enviar uma mensagem técnica explicitamente solicitada, sem repetir no mesmo run")
    parser.add_argument("--preview", action="store_true", help="Enviar uma única prévia real sem alegar promoção aprovada")
    args = parser.parse_args()
    run(args.connect, args.limit, args.test, args.preview, verify_only=args.verify, send_media_test=args.media_test,
        reset_session=args.reset_session)

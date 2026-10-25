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


def run(connect_only=False, limit=20, send_test=False):
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise ValueError("Este comando deve ser executado no GitHub Actions")
    if send_test and not connect_only:
        raise ValueError("O teste exige o modo explícito de conexão")
    config = configure(limit)
    env = dict(os.environ, WHATSAPP_AUTH_MODE="supabase", WHATSAPP_ALLOW_QR=str(connect_only and not send_test).lower(),
               WHATSAPP_BRIDGE_TOKEN=secrets.token_hex(32), WHATSAPP_RUNNER_BRIDGE="true")
    process = subprocess.Popen(["node", "publishers/whatsapp_bridge.cjs"], env=env)
    try:
        deadline = time.monotonic() + (600 if connect_only and not send_test else 180 if send_test else 300)
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
            if send_test:
                # O publicador deve usar a mesma ponte privada criada neste job.
                previous = {key:os.environ.get(key) for key in ("WHATSAPP_BRIDGE_TOKEN","WHATSAPP_RUNNER_BRIDGE")}
                try:
                    for key in previous: os.environ[key] = env[key]
                    send_test_once(config)
                finally:
                    for key,value in previous.items():
                        if value is None: os.environ.pop(key,None)
                        else: os.environ[key] = value
            print("Sessão da nuvem conectada e persistida." + ("" if send_test else " Nenhuma mensagem enviada."), flush=True)
            if send_test:
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
    args = parser.parse_args()
    run(args.connect, args.limit, args.test)

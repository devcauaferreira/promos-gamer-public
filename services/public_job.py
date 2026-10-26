"""Executa tarefas com credenciais sem expor sua saída nos logs públicos do Actions."""
import argparse
import json
import subprocess
import sys
from pathlib import Path


def safe_summary():
    """Mostra apenas contagens e estados conhecidos, nunca URLs ou erros externos."""
    sources_file = Path("reports/sources.json")
    offers_file = Path("reports/latest.json")
    if not sources_file.is_file() or not offers_file.is_file():
        return
    sources = json.loads(sources_file.read_text(encoding="utf-8"))
    offers = json.loads(offers_file.read_text(encoding="utf-8"))
    allowed_stores = {"kabum", "mercadolivre", "amazon", "magalu", "pichau"}
    allowed_states = {"operational", "ready_to_validate", "needs_authorized_feed",
                      "feed_missing", "oauth_pending", "needs_credentials", "disabled",
                      "access_denied", "rate_limited", "backoff", "review_only",
                      "temporarily_unavailable", "network_error", "auth_required"}
    for row in sources:
        store, state = row.get("store"), row.get("state")
        if store in allowed_stores:
            print(f"Fonte {store}: {state if state in allowed_states else 'indisponível'}", flush=True)
    approved = sum(row.get("decision", {}).get("status") == "approved" for row in offers)
    no_history = sum("Histórico insuficiente" in row.get("decision", {}).get("reasons", ()) for row in offers)
    print(f"Produtos avaliados: {len(offers)}; ofertas aprovadas: {approved}; sem histórico anterior: {no_history}", flush=True)
    from services.monitoring import summarize
    summary = summarize(offers)
    for store, count in summary['observations'].items():
        print(f"Observações registradas {store}: {count}", flush=True)
    print(f"Envios confirmados: {summary['sent']}; erros: {summary['errors']}; pendências de persistência: {summary['persistence_errors']}", flush=True)
    for reason, count in summary['reasons'].items():
        print(f"Filtro: {reason}; produtos: {count}", flush=True)
    for code, count in summary['source_failures'].items():
        print(f"Pendência: {code}; produtos: {count}", flush=True)


def run_job(mode, limit=20, send_test=False, send_preview=False):
    if mode not in ("collect", "publish", "connect"):
        raise ValueError("Tarefa não suportada")
    if (not 1 <= limit <= 500 or ((send_test or send_preview) and mode != "connect")
            or (send_test and send_preview)):
        raise ValueError("Opções inválidas")
    if mode == "collect":
        command = [sys.executable, "cloud_run.py", "--check-candidates", "--limit", str(limit)]
    elif mode == "publish":
        command = [sys.executable, "whatsapp_cloud_job.py", "--limit", str(limit)]
    else:
        command = [sys.executable, "whatsapp_cloud_job.py", "--connect"]
        if send_test:
            command.append("--test")
        if send_preview:
            command.append("--preview")
    # Não enviar este arquivo a artifacts/caches: pode conter dados privados.
    # O runner é efêmero; banco e sessão continuam persistidos no Supabase.
    folder = Path("reports")
    folder.mkdir(exist_ok=True)
    report_file = folder / 'latest.json'
    def report_version():
        try:
            stat = report_file.stat()
            return stat.st_mtime_ns, stat.st_size
        except FileNotFoundError:
            return None
    previous_report = report_version()
    print(f"Tarefa {mode} iniciada; saída detalhada restrita ao runner.", flush=True)
    with (folder / "cloud-job-private.log").open("ab") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    # Uma falha antes da coleta/publicação não pode apresentar o relatório
    # antigo de outra etapa como resultado desta execução.
    if mode in ('collect', 'publish') and report_version() != previous_report:
        try:
            safe_summary()
        except (OSError, ValueError, TypeError):
            print("Resumo indisponível; dados detalhados mantidos no runner.", flush=True)
    if result.returncode:
        print(f"Tarefa {mode} falhou. Execute o diagnóstico em ambiente privado.", flush=True)
        return 1
    print(f"Tarefa {mode} concluída.", flush=True)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("collect", "publish", "connect"))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    try:
        code = run_job(args.mode, args.limit, args.test, args.preview)
    except Exception:
        # Mensagens de exceção podem conter URLs, credenciais e IDs privados.
        print("Não foi possível executar a tarefa. Consulte a configuração em ambiente privado.", flush=True)
        code = 1
    raise SystemExit(code)

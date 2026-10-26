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
    operation_file = Path('reports/operation.json')
    if operation_file.is_file():
        from services.monitoring import _safe_operation
        operation = _safe_operation(json.loads(operation_file.read_text(encoding='utf-8')))
        policy = operation.get('policy', {})
        print(f"Política efetiva: {policy.get('minimum_discount_percent')}%; janela {policy.get('history_days')} dias; lote {policy.get('products_per_run')}", flush=True)
    for store, count in summary['observations'].items():
        print(f"Observações registradas {store}: {count}", flush=True)
    print(f"Envios confirmados: {summary['sent']}; erros: {summary['errors']}; pendências de persistência: {summary['persistence_errors']}", flush=True)
    for reason, count in summary['reasons'].items():
        print(f"Filtro: {reason}; produtos: {count}", flush=True)
    for code, count in summary['source_failures'].items():
        print(f"Pendência: {code}; produtos: {count}", flush=True)
    for store, counts in summary['funnel'].items():
        print(f"Etapas {store}: coletados={counts['collected']}; disponíveis={counts['available']}; com histórico={counts['history_ready']}; atingiram desconto={counts['discount_met']}; aprovados={counts['approved']}; enviados={counts['sent']}", flush=True)
    for code, count in summary['delivery_failures'].items():
        print(f'Falha de entrega: {code}; tentativas: {count}', flush=True)


def safe_failure_code(log_path):
    """Classify a private child log into a fixed, non-sensitive diagnostic code."""
    try:
        text = Path(log_path).read_text(encoding="utf-8", errors="replace")[-200_000:]
    except OSError:
        return "child_failed"
    import re
    match = re.search(r"Bridge startup diagnostic: (whatsapp_[a-z0-9_]+)", text)
    if match:
        allowed = {
            "whatsapp_session_key_invalid", "whatsapp_session_archive_invalid",
            "whatsapp_browser_executable_missing", "whatsapp_browser_launch_failed",
            "whatsapp_browser_protocol_error", "whatsapp_web_initialization_timeout",
            "whatsapp_session_network_error", "whatsapp_initialization_failed",
            "whatsapp_dependency_missing",
            *(f"whatsapp_session_http_{status}" for status in (401, 403, 404, 409, 429, 500, 502, 503, 504)),
        }
        if match.group(1) in allowed:
            return match.group(1)
    known = (
        ("HTTP 409", "supabase_state_conflict"),
        ("HTTP 401", "supabase_auth_http_401"),
        ("HTTP 403", "supabase_auth_http_403"),
        ("HTTP 429", "supabase_rate_limited"),
        ("Falha ao consultar", "supabase_network_error"),
        ("banco local existente", "remote_state_missing"),
        ("Snapshot remoto", "remote_snapshot_invalid"),
        ("remota inesperada", "supabase_state_conflict"),
        ("nuvem precisa de autoriza", "whatsapp_reauthorization_required"),
        ("Falha na autenticação", "whatsapp_auth_failure"),
        ("ficou pronto no prazo", "whatsapp_session_not_ready"),
        ("Ponte encerrou", "whatsapp_bridge_stopped"),
        ("Nenhuma foto de produto validado disponível", "media_image_missing"),
        ("Foto indisponível antes do envio", "media_image_missing"),
    )
    for phrase, code in known:
        if phrase in text:
            return code
    if "whatsapp_confirmation_missing" in text:
        return "whatsapp_confirmation_missing"
    if "whatsapp_send_failed" in text:
        return "whatsapp_send_failed"
    if "HTTP Error 409" in text:
        return "supabase_state_conflict"
    if "HTTP Error 401" in text or "HTTP Error 403" in text:
        return "remote_service_auth_error"
    if "Traceback (most recent call last)" in text:
        return "child_exception"
    return "child_failed"


def run_job(mode, limit=20, send_test=False, send_preview=False, send_media_test=False):
    if mode not in ("collect", "publish", "connect", "verify"):
        raise ValueError("Tarefa não suportada")
    if (not 1 <= limit <= 500 or ((send_test or send_preview or send_media_test) and mode != "connect")
            or sum(map(bool, (send_test, send_preview, send_media_test))) > 1):
        raise ValueError("Opções inválidas")
    if mode == "collect":
        command = [sys.executable, "cloud_run.py", "--check-candidates", "--limit", str(limit)]
    elif mode == "publish":
        command = [sys.executable, "whatsapp_cloud_job.py", "--limit", str(limit)]
    elif mode == 'verify':
        command = [sys.executable, 'whatsapp_cloud_job.py', '--verify']
    else:
        command = [sys.executable, "whatsapp_cloud_job.py", "--connect"]
        if send_test:
            command.append("--test")
        if send_preview:
            command.append("--preview")
        if send_media_test:
            command.append('--media-test')
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
        print(f"Diagnóstico seguro da tarefa: {safe_failure_code(folder / 'cloud-job-private.log')}", flush=True)
        print(f"Tarefa {mode} falhou. Execute o diagnóstico em ambiente privado.", flush=True)
        return 1
    print(f"Tarefa {mode} concluída.", flush=True)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("collect", "publish", "connect", "verify"))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument('--media-test', action='store_true')
    args = parser.parse_args()
    try:
        code = run_job(args.mode, args.limit, args.test, args.preview, args.media_test)
    except Exception:
        # Mensagens de exceção podem conter URLs, credenciais e IDs privados.
        print("Não foi possível executar a tarefa. Consulte a configuração em ambiente privado.", flush=True)
        code = 1
    raise SystemExit(code)

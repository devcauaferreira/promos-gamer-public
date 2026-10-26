"""Executa um único ciclo no runner; persiste o SQLite fora da máquina efêmera."""
import argparse
import json
from contextlib import closing
from pathlib import Path

from database.models import connect
from services.cloud import CloudState
from services.secrets import secret


def configure(limit=None):
    raw = secret("PROMOS_SETTINGS_JSON")
    if not raw:
        raise ValueError("Cadastre PROMOS_SETTINGS_JSON nos secrets do GitHub")
    settings = json.loads(raw)
    if limit is not None:
        if not 1 <= limit <= 500:
            raise ValueError("O limite do ciclo deve estar entre 1 e 500")
        settings.setdefault("discovery", {})["max_products_per_run"] = limit
    settings["database_path"] = "database/promos.sqlite3"
    Path("settings.json").write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
    # Cadastro inicial opcional; descoberta e catálogo ficam no snapshot remoto.
    products = json.loads(secret("PROMOS_PRODUCTS_JSON") or "[]")
    Path("products.json").write_text(json.dumps(products, ensure_ascii=False), encoding="utf-8")
    from services.settings import load_settings
    config, _ = load_settings()
    return config


def execute(send=False, check_candidates=False, limit=None):
    if send and check_candidates:
        raise ValueError("Use --send ou --check-candidates, não ambos")
    config = configure(limit=limit)
    if send:
        from publishers.whatsapp import validate_publish_bridge
        validate_publish_bridge()
    state = CloudState(config.database_path)
    state.restore()
    from services.monitoring import start_run, finish_run
    from uuid import uuid4
    import os
    run_id = uuid4().hex
    with closing(connect(config.database_path)) as db:
        start_run(db, run_id, 'publish' if send else 'collect',
                  os.environ.get('MONITOR_TRIGGER') or os.environ.get('GITHUB_EVENT_NAME', 'local'))
        state.checkpoint(db)
    from services.runner import cycle
    report, completed = [], False
    try:
        report = cycle(send=send, checkpoint=state.checkpoint, queued_only=send)
        completed = True
    finally:
        # Se o processo for morto, reservas de envio já foram persistidas antes da rede.
        with closing(connect(config.database_path)) as db:
            delivery_problem = send and any(row.get('send_error') or row.get('persistence_error') for row in report)
            status = 'requires_attention' if completed and delivery_problem else 'completed' if completed else 'failed'
            finish_run(db, run_id, status, report)
            state.checkpoint(db)
    if check_candidates:
        from services.outbox import pending
        with closing(connect(config.database_path)) as db:
            approved = len(pending(db))
        Path("reports/has_candidates.txt").write_text("true\n" if approved else "false\n", encoding="ascii")
        print(f"Ofertas aprovadas nesta coleta: {approved}", flush=True)
    return 1 if delivery_problem else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--check-candidates", action="store_true",
                        help="Coleta e indica se há oferta aprovada antes de iniciar o WhatsApp")
    parser.add_argument("--limit", type=int, help="Limita produtos descobertos neste ciclo de validação")
    args = parser.parse_args()
    if args.send and args.check_candidates:
        parser.error("Use --send ou --check-candidates, não ambos")
    raise SystemExit(execute(args.send, args.check_candidates, args.limit))

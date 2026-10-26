"""Resumo operacional sem URLs, credenciais ou identificadores do grupo."""
import json
from collections import Counter
from datetime import datetime, timezone

REASONS = ('Histórico insuficiente', 'Queda abaixo do mínimo exigido',
           'Oferta indisponível', 'Oferta publicada recentemente',
           'Condições de pagamento desconhecidas', 'Disponibilidade não confirmada')
SOURCE_FAILURES = ('catalog_mapping_required', 'catalog_item_missing', 'needs_authorized_feed',
                   'access_denied', 'auth_required', 'oauth_pending', 'network_error',
                   'rate_limited', 'invalid_response', 'wholesale_review',
                   'price_unconfirmed', 'seller_unconfirmed', 'item_unavailable')


def summarize(report):
    reasons = Counter(reason for row in report for reason in row.get('decision', {}).get('reasons', ())
                      if reason in REASONS)
    observed = Counter(row.get('store') for row in report if row.get('observation_recorded')
                       and row.get('store') in ('mercadolivre', 'amazon', 'kabum', 'magalu', 'pichau'))
    return {'evaluated': len(report), 'observations': dict(observed),
            'approved': sum(row.get('decision', {}).get('status') == 'approved' for row in report),
            'sent': sum(row.get('send_status') == 'sent' for row in report),
            'errors': sum(bool(row.get('error') or row.get('send_error')) for row in report),
            'persistence_errors': sum(bool(row.get('persistence_error')) for row in report),
            'reasons': dict(reasons),
            'source_failures': dict(Counter(row.get('status') for row in report
                                           if row.get('status') in SOURCE_FAILURES))}


def start_run(db, run_id, mode, event):
    db.execute('''CREATE TABLE IF NOT EXISTS monitor_runs (
        run_id TEXT PRIMARY KEY, mode TEXT NOT NULL, event TEXT NOT NULL,
        started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, summary_json TEXT)''')
    db.execute("INSERT INTO monitor_runs VALUES (?,?,?,?,NULL,'running',NULL)",
               (run_id, mode, event, datetime.now(timezone.utc).isoformat()))
    db.commit()


def finish_run(db, run_id, status, report):
    db.execute('UPDATE monitor_runs SET finished_at=?,status=?,summary_json=? WHERE run_id=?',
               (datetime.now(timezone.utc).isoformat(), status, json.dumps(summarize(report), ensure_ascii=False), run_id))
    # Mantém somente o histórico operacional recente; não remove preços nem entregas.
    db.execute('DELETE FROM monitor_runs WHERE run_id NOT IN '
               '(SELECT run_id FROM monitor_runs ORDER BY started_at DESC LIMIT 500)')
    db.commit()

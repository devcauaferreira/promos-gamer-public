"""Resumo operacional sem URLs, credenciais ou identificadores do grupo."""
import json
import math
from collections import Counter
from datetime import datetime, timezone

REASONS = ('Histórico insuficiente', 'Queda abaixo do mínimo exigido',
           'Oferta indisponível', 'Oferta publicada recentemente',
           'Condições de pagamento desconhecidas', 'Disponibilidade não confirmada')
SOURCE_FAILURES = ('catalog_mapping_required', 'catalog_item_missing', 'needs_authorized_feed',
                   'access_denied', 'auth_required', 'oauth_pending', 'network_error',
                   'rate_limited', 'invalid_response', 'wholesale_review',
                   'temporarily_unavailable',
                   'price_unconfirmed', 'seller_unconfirmed', 'item_unavailable')
STORES = ('mercadolivre', 'amazon', 'kabum', 'magalu', 'pichau')
SOURCE_MODES = ('official_api', 'official_catalog', 'authorized_feed', 'legacy_web',
                'public_catalog_review', 'disabled', 'unknown')
SOURCE_STATES = ('operational', 'ready_to_validate', 'needs_authorized_feed', 'feed_missing',
                 'oauth_pending', 'needs_credentials', 'disabled', 'access_denied',
                 'rate_limited', 'backoff', 'review_only', 'temporarily_unavailable',
                 'network_error', 'auth_required', 'unknown')


def _number(value, *, integer=False):
    if type(value) not in ((int,) if integer else (int, float)):
        return None
    try:
        return value if math.isfinite(value) and value >= 0 else None
    except OverflowError:
        return None


def _date(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc).isoformat() if parsed.utcoffset() is not None else None
    except (ValueError, OverflowError):
        return None


def _safe_operation(value):
    """Whitelista também o argumento opcional de finish_run; nunca copia texto livre."""
    if not isinstance(value, dict):
        return {}
    result = {}
    policy = value.get('policy', {})
    if isinstance(policy, dict):
        result['policy'] = {key: number for key in ('minimum_discount_percent', 'history_days',
                              'minimum_history_days', 'products_per_run', 'interval_seconds')
                            if (number := _number(policy.get(key))) is not None}
    coverage = value.get('coverage', {})
    if isinstance(coverage, dict):
        clean = {key: number for key in ('active_total', 'estimated_sweep_minutes')
                 if (number := _number(coverage.get(key))) is not None}
        clean['stores'] = {}
        rows = coverage.get('stores', {})
        if isinstance(rows, dict):
            for store, row in rows.items():
                if store not in STORES or not isinstance(row, dict):
                    continue
                entry = {key: number for key in ('active', 'checked', 'unchecked', 'oldest_check_age_minutes')
                         if (number := _number(row.get(key))) is not None}
                entry['oldest_checked_at'] = _date(row.get('oldest_checked_at'))
                clean['stores'][store] = entry
        result['coverage'] = clean
    sources = value.get('sources', {})
    if isinstance(sources, dict):
        result['sources'] = {store: {
            'mode': row.get('mode') if row.get('mode') in SOURCE_MODES else 'unknown',
            'state': row.get('state') if row.get('state') in SOURCE_STATES else 'unknown'}
            for store, row in sources.items() if store in STORES and isinstance(row, dict)}
    queues = value.get('queues', {})
    if isinstance(queues, dict):
        result['queues'] = {key: number for key in ('pending', 'uncertain', 'uncertain_dispatches')
                            if (number := _number(queues.get(key), integer=True)) is not None}
    whatsapp = value.get('whatsapp', {})
    if isinstance(whatsapp, dict) and (checked := _date(whatsapp.get('checked_at'))):
        result['whatsapp'] = {'checked_at': checked}
        for key in ('ready', 'group_found', 'session_saved'):
            if type(whatsapp.get(key)) is bool:
                result['whatsapp'][key] = whatsapp[key]
    return result


def operation_summary(db, config, settings, source_rows=()):
    """Contexto efetivo do ciclo e cobertura da fila, sem consultar serviços externos."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    limit = int(settings.get('discovery', {}).get('max_products_per_run', 20))
    interval = int(settings.get('interval_seconds', 300))
    result = {'policy': {'minimum_discount_percent': config.minimum_discount_percent,
                        'history_days': config.history_days,
                        'minimum_history_days': config.minimum_history_days,
                        'products_per_run': limit, 'interval_seconds': interval},
              'coverage': {'active_total': 0, 'estimated_sweep_minutes': 0, 'stores': {}},
              'sources': {}, 'queues': {'pending': 0, 'uncertain': 0, 'uncertain_dispatches': 0}}
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'tracked_products' in tables:
        cutoff = now - timedelta(days=7)
        for store, data, last_seen, last_checked in db.execute(
                'SELECT store,data,last_seen,last_checked FROM tracked_products'):
            if store not in STORES:
                continue
            seen = _date(last_seen)
            if not seen or datetime.fromisoformat(seen) < cutoff:
                continue
            try:
                entry = json.loads(data)
                if not isinstance(entry, dict) or entry.get('enabled') is False:
                    continue
            except (ValueError, TypeError):
                continue
            row = result['coverage']['stores'].setdefault(store,
                  {'active': 0, 'checked': 0, 'unchecked': 0, 'oldest_checked_at': None})
            row['active'] += 1
            checked = _date(last_checked)
            row['checked' if checked else 'unchecked'] += 1
            if checked and (not row['oldest_checked_at'] or checked < row['oldest_checked_at']):
                row['oldest_checked_at'] = checked
        for row in result['coverage']['stores'].values():
            result['coverage']['active_total'] += row['active']
            if row['oldest_checked_at']:
                row['oldest_check_age_minutes'] = max(0, round(
                    (now - datetime.fromisoformat(row['oldest_checked_at'])).total_seconds() / 60, 1))
        if limit > 0:
            result['coverage']['estimated_sweep_minutes'] = round(
                math.ceil(result['coverage']['active_total'] / limit) * interval / 60, 1)
    if 'pending_offers' in tables:
        for state, count in db.execute('SELECT state,COUNT(*) FROM pending_offers GROUP BY state'):
            if state in ('pending', 'uncertain'):
                result['queues'][state] = count
    if 'dispatches' in tables:
        result['queues']['uncertain_dispatches'] = db.execute(
            "SELECT COUNT(*) FROM dispatches WHERE state='uncertain'").fetchone()[0]
    for store, options in settings.get('sources', {}).items():
        if store in STORES and isinstance(options, dict):
            result['sources'][store] = {'mode': options.get('mode', 'unknown'), 'state': 'unknown'}
    for row in source_rows:
        if isinstance(row, dict) and row.get('store') in STORES:
            result['sources'][row['store']] = {'mode': row.get('mode'), 'state': row.get('state')}
    if 'whatsapp_health' in tables:
        row = db.execute('SELECT checked_at,ready,group_found,session_saved FROM whatsapp_health '
                         'ORDER BY checked_at DESC LIMIT 1').fetchone()
        if row:
            result['whatsapp'] = dict(zip(('checked_at', 'ready', 'group_found', 'session_saved'),
                                        (row[0], bool(row[1]), bool(row[2]), bool(row[3]))))
    return _safe_operation(result)


def summarize(report):
    reasons = Counter(reason for row in report for reason in row.get('decision', {}).get('reasons', ())
                      if reason in REASONS)
    observed = Counter(row.get('store') for row in report if row.get('observation_recorded')
                       and row.get('store') in ('mercadolivre', 'amazon', 'kabum', 'magalu', 'pichau'))
    funnel = {}
    for row in report:
        store = row.get('store')
        if store not in STORES:
            continue
        stages = funnel.setdefault(store, {key: 0 for key in
                    ('attempted', 'collected', 'observed', 'available', 'history_ready',
                     'discount_met', 'approved', 'sent')})
        stages['attempted'] += 1
        offer, decision = row.get('offer', {}), row.get('decision', {})
        offer = offer if isinstance(offer, dict) else {}
        decision = decision if isinstance(decision, dict) else {}
        stages['collected'] += bool(offer)
        stages['observed'] += row.get('observation_recorded') is True
        stages['available'] += offer.get('available') is True
        samples = _number(decision.get('history_samples'), integer=True)
        stages['history_ready'] += bool(samples and 'Histórico insuficiente' not in decision.get('reasons', ()))
        stages['discount_met'] += bool(_number(decision.get('discount_percent')) is not None
                                      and 'Queda abaixo do mínimo exigido' not in decision.get('reasons', ()))
        stages['approved'] += decision.get('status') == 'approved'
        stages['sent'] += row.get('send_status') == 'sent'
    return {'evaluated': len(report), 'observations': dict(observed), 'funnel': funnel,
            'approved': sum(row.get('decision', {}).get('status') == 'approved' for row in report),
            'sent': sum(row.get('send_status') == 'sent' for row in report),
            'errors': sum(bool(row.get('error') or row.get('send_error')) for row in report),
            'persistence_errors': sum(bool(row.get('persistence_error')) for row in report),
            'reasons': dict(reasons),
            'source_failures': dict(Counter(row.get('status') for row in report
                                           if row.get('status') in SOURCE_FAILURES)),
            'delivery_failures': dict(Counter(row.get('send_error') for row in report
                  if row.get('send_error') in ('whatsapp_send_failed', 'whatsapp_confirmation_missing',
                                              'whatsapp_transport_unknown', 'whatsapp_bridge_http_error')))}


def start_run(db, run_id, mode, event):
    db.execute('''CREATE TABLE IF NOT EXISTS monitor_runs (
        run_id TEXT PRIMARY KEY, mode TEXT NOT NULL, event TEXT NOT NULL,
        started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, summary_json TEXT)''')
    db.execute("INSERT INTO monitor_runs VALUES (?,?,?,?,NULL,'running',NULL)",
               (run_id, mode, event, datetime.now(timezone.utc).isoformat()))
    db.commit()


def finish_run(db, run_id, status, report, operation=None):
    summary = summarize(report)
    if operation is not None:
        summary['operation'] = _safe_operation(operation)
    db.execute('UPDATE monitor_runs SET finished_at=?,status=?,summary_json=? WHERE run_id=?',
               (datetime.now(timezone.utc).isoformat(), status, json.dumps(summary, ensure_ascii=False), run_id))
    # Mantém somente o histórico operacional recente; não remove preços nem entregas.
    db.execute('DELETE FROM monitor_runs WHERE run_id NOT IN '
               '(SELECT run_id FROM monitor_runs ORDER BY started_at DESC LIMIT 500)')
    db.commit()

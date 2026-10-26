import json
import base64
import contextlib
import importlib.util
import io
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from config import Config
from database.models import connect
from services.monitoring import finish_run, operation_summary, start_run, summarize


class MonitoringTests(unittest.TestCase):
    def test_persisted_run_distinguishes_completion_and_no_eligible_deals(self):
        rows = [{'decision': {'status': 'pending_review', 'reasons': ['Queda abaixo do mínimo exigido', 'private-detail']}}]
        with closing(connect(':memory:')) as db:
            start_run(db, 'test-run', 'collect', 'schedule')
            finish_run(db, 'test-run', 'completed', rows)
            status, payload = db.execute('SELECT status,summary_json FROM monitor_runs').fetchone()
            self.assertEqual(status, 'completed')
            summary = json.loads(payload)
            self.assertEqual(summary['evaluated'], 1)
            self.assertEqual(summary['approved'], 0)
            self.assertEqual(summary['reasons'], {'Queda abaixo do mínimo exigido': 1})
            self.assertNotIn('private-detail', payload)

    def test_failed_collection_is_counted_without_exposing_error(self):
        value = summarize([{'error': 'secret URL', 'status': 'catalog_mapping_required'}, {'send_status': 'sent'}])
        self.assertEqual(value['errors'], 1)
        self.assertEqual(value['sent'], 1)
        self.assertEqual(value['source_failures'], {'catalog_mapping_required': 1})
        self.assertNotIn('secret', json.dumps(value))

    def test_confirmed_delivery_and_persistence_failure_are_distinct(self):
        value = summarize([{'send_status': 'sent', 'persistence_error': 'private database detail'}])
        self.assertEqual(value['sent'], 1)
        self.assertEqual(value['errors'], 0)
        self.assertEqual(value['persistence_errors'], 1)
        self.assertNotIn('private', json.dumps(value))

    def test_operation_records_actual_policy_coverage_and_queues_without_private_data(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(minutes=30)).isoformat()
        with closing(connect(':memory:')) as db:
            db.executescript('''CREATE TABLE tracked_products (
                store TEXT,data TEXT,last_seen TEXT,last_checked TEXT);
                CREATE TABLE pending_offers (state TEXT);
                CREATE TABLE dispatches (state TEXT);
                CREATE TABLE whatsapp_health (checked_at TEXT,ready INTEGER,group_found INTEGER,session_saved INTEGER);''')
            rows = [('kabum', {'id': 'private-id'}, now.isoformat(), old),
                    ('kabum', {'url': 'https://private.example/item'}, now.isoformat(), None),
                    ('mercadolivre', {}, now.isoformat(), old),
                    ('kabum', {'enabled': False}, now.isoformat(), None),
                    ('kabum', {}, (now - timedelta(days=8)).isoformat(), None),
                    ('private-store', {}, now.isoformat(), None)]
            db.executemany('INSERT INTO tracked_products VALUES (?,?,?,?)',
                           [(store, json.dumps(data), seen, checked) for store, data, seen, checked in rows])
            db.executemany('INSERT INTO pending_offers VALUES (?)', [('pending',), ('uncertain',), ('sent',)])
            db.execute("INSERT INTO dispatches VALUES ('uncertain')")
            db.execute('INSERT INTO whatsapp_health VALUES (?,1,1,1)', (now.isoformat(),))
            settings = {'discovery': {'max_products_per_run': 2}, 'interval_seconds': 300,
                        'sources': {'amazon': {'mode': 'authorized_feed', 'feed_path': 'private-file'}}}
            operation = operation_summary(db, Config(), settings, [
                {'store': 'kabum', 'mode': 'legacy_web', 'state': 'operational', 'error': 'private-token'},
                {'store': 'private-store', 'mode': 'private-mode', 'state': 'private-state'}])
            self.assertEqual(operation['policy']['minimum_discount_percent'], 25)
            self.assertEqual(operation['policy']['history_days'], 30)
            self.assertEqual(operation['policy']['products_per_run'], 2)
            self.assertEqual(operation['coverage']['active_total'], 3)
            self.assertEqual(operation['coverage']['estimated_sweep_minutes'], 10)
            self.assertEqual(operation['coverage']['stores']['kabum']['unchecked'], 1)
            self.assertEqual(operation['coverage']['stores']['kabum']['oldest_checked_at'], old)
            self.assertEqual(operation['queues'], {'pending': 1, 'uncertain': 1, 'uncertain_dispatches': 1})
            self.assertTrue(operation['whatsapp']['ready'])
            self.assertEqual(operation['sources']['kabum']['state'], 'operational')
            self.assertNotIn('private', json.dumps(operation))

    def test_finish_run_sanitizes_even_an_arbitrary_operation_argument(self):
        operation = {'private-key': 'private-secret',
                     'policy': {'history_days': 30, 'interval_seconds': float('inf'), 'private': 'secret'},
                     'coverage': {'active_total': 2, 'stores': {'kabum': {
                         'active': 2, 'oldest_checked_at': 'private-token', 'url': 'private-url'}}},
                     'sources': {'kabum': {'mode': 'private-mode', 'state': 'private-state', 'error': 'private-error'}},
                     'queues': {'pending': 'private-pending'},
                     'whatsapp': {'checked_at': 'private-date'}}
        with closing(connect(':memory:')) as db:
            start_run(db, 'test', 'collect', 'self_chain')
            finish_run(db, 'test', 'completed', [], operation=operation)
            payload = db.execute('SELECT summary_json FROM monitor_runs').fetchone()[0]
            value = json.loads(payload)['operation']
            self.assertEqual(value['policy'], {'history_days': 30})
            self.assertEqual(value['sources']['kabum'], {'mode': 'unknown', 'state': 'unknown'})
            self.assertNotIn('private', payload)
            self.assertNotIn('Infinity', payload)

    def test_funnel_distinguishes_missing_history_and_availability_from_sending(self):
        rows = [{'store': 'kabum', 'observation_recorded': True, 'offer': {'available': True},
                 'decision': {'history_samples': 4, 'discount_percent': 25, 'reasons': (), 'status': 'approved'},
                 'send_status': 'sent'},
                {'store': 'kabum', 'observation_recorded': True, 'offer': {'available': False},
                 'decision': {'history_samples': 0, 'discount_percent': None, 'status': 'pending_review',
                              'reasons': ['Histórico insuficiente', 'Disponibilidade não confirmada']}},
                {'store': 'kabum', 'error': 'private-error'}]
        result = summarize(rows)
        self.assertEqual(result['funnel']['kabum'], {
            'attempted': 3, 'collected': 2, 'observed': 2, 'available': 1,
            'history_ready': 1, 'discount_met': 1, 'approved': 1, 'sent': 1})
        self.assertNotIn('private', json.dumps(result))

    def test_status_uses_last_finished_summary_while_a_new_cycle_is_running(self):
        spec = importlib.util.spec_from_file_location('promos_status_cloud',
                  Path(__file__).resolve().parents[1] / 'status-cloud.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with closing(connect(':memory:')) as db:
            start_run(db, 'complete', 'collect', 'self_chain')
            finish_run(db, 'complete', 'completed', [{'decision': {'status': 'pending_review', 'reasons': []}}])
            start_run(db, 'active', 'collect', 'self_chain')
            payload = base64.b64encode(db.serialize()).decode()
        output = io.StringIO()
        with patch.object(module, 'cloud_request', return_value={'payload': payload}), contextlib.redirect_stdout(output):
            module.main()
        self.assertIn('Último ciclo concluído', output.getvalue())
        self.assertIn('Avaliados: 1', output.getvalue())
        self.assertIn('estado: running', output.getvalue())

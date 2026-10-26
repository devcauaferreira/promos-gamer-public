import json
import unittest
from contextlib import closing

from database.models import connect
from services.monitoring import finish_run, start_run, summarize


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

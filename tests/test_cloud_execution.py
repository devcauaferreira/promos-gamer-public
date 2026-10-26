import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from cloud_run import execute
from config import Config
from database.models import connect


class CloudExecutionTests(unittest.TestCase):
    def test_uncertain_send_persists_attention_state_and_fails_job(self):
        for result in ({'send_error': 'private send detail'},
                       {'send_status': 'sent', 'persistence_error': 'private persistence detail'}):
            with self.subTest(result=result), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'state.sqlite3'
                with patch('cloud_run.configure', return_value=Config(database_path=path)), \
                     patch('cloud_run.CloudState') as state, \
                     patch('services.runner.cycle', return_value=[result]), \
                     patch('publishers.whatsapp.validate_publish_bridge'):
                    self.assertEqual(execute(send=True), 1)
                    state.return_value.checkpoint.assert_called()
                    with closing(connect(path)) as db:
                        status, payload = db.execute('SELECT status,summary_json FROM monitor_runs').fetchone()
                    self.assertEqual(status, 'requires_attention')
                    self.assertNotIn('private', payload)
                    self.assertEqual(json.loads(payload)['sent'], int(result.get('send_status') == 'sent'))

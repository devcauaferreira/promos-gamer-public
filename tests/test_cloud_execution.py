import json
import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from cloud_run import execute
from config import Config
from database.models import connect
from datetime import datetime, timedelta, timezone
from collectors.base import SourceError
from collectors.catalog import canonical_product
from services.price_history import record_price
from services.runner import cycle


class CloudExecutionTests(unittest.TestCase):
    def test_uncertain_send_persists_attention_state_and_fails_job(self):
        for result in ({'send_error': 'private send detail'},
                       {'send_status': 'sent', 'persistence_error': 'private persistence detail'},
                       {'status': 'network_error', 'error': 'private revalidation detail'}):
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

    def test_revalidation_failure_keeps_real_outbox_candidate_pending_and_fails_job(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as folder:
            os.chdir(folder)
            try:
                now = datetime.now(timezone.utc)
                url = 'https://www.pichau.com.br/ssd-kingston-1tb'
                key, _ = canonical_product(url)
                offer = {'url': url, 'title': 'SSD Kingston 1TB', 'seller_id': 'Pichau',
                         'shipped_by': 'Pichau', 'price_cents': 36000, 'currency': 'BRL',
                         'available': True, 'payment_terms': 'PIX', 'observed_at': now.isoformat()}
                Path('feed.json').write_text(json.dumps({'schema_version': 1, 'store': 'pichau',
                                                        'offers': [offer]}), encoding='utf-8')
                settings = {'database_path': 'state.sqlite3', 'whatsapp_group_id': 'test@g.us',
                            'sources': {store: {'mode': 'disabled'} for store in
                                        ('kabum', 'amazon', 'mercadolivre', 'magalu')},
                            'discovery': {'enabled': False}}
                settings['sources']['pichau'] = {'mode': 'authorized_feed', 'feed_path': 'feed.json',
                                                'authorization_reference': 'Test fixture'}
                Path('settings.json').write_text(json.dumps(settings), encoding='utf-8')
                Path('products.json').write_text(json.dumps([{'id': key, 'store': 'pichau', 'url': url}]),
                                                 encoding='utf-8')
                first = cycle()[0]
                with closing(connect('state.sqlite3')) as db:
                    record_price(db, 'pichau', first['offer']['product_id'], 49000, now - timedelta(days=1))
                self.assertEqual(cycle()[0]['decision']['status'], 'approved')
                with patch('cloud_run.configure', return_value=Config(database_path=Path('state.sqlite3'))), \
                     patch('cloud_run.CloudState'), patch('publishers.whatsapp.validate_publish_bridge'), \
                     patch('collectors.feed.AuthorizedFeed.collect',
                           side_effect=SourceError('network_error', 'private connection detail')), \
                     patch('services.runner.publish') as publish:
                    self.assertEqual(execute(send=True), 1)
                    publish.assert_not_called()
                with closing(connect('state.sqlite3')) as db:
                    self.assertEqual(db.execute('SELECT state FROM pending_offers').fetchone()[0], 'pending')
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM publications').fetchone()[0], 0)
                    status, payload = db.execute('SELECT status,summary_json FROM monitor_runs').fetchone()
                self.assertEqual(status, 'requires_attention')
                self.assertEqual(json.loads(payload)['errors'], 1)
                self.assertNotIn('private', payload)
            finally:
                os.chdir(previous)

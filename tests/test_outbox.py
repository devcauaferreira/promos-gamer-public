import json
import os
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from database.models import Offer, connect
from services.outbox import enqueue, ensure_outbox, pending
from services.price_history import record_price
from services.runner import cycle


class OutboxTests(unittest.TestCase):
    def test_cycle_preserves_retryable_and_confirmed_outbox_states_on_checkpoint_failures(self):
        for failure in ('before_send', 'after_confirmation'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                previous = Path.cwd()
                os.chdir(folder)
                try:
                    now = datetime.now(timezone.utc)
                    rows = [{'url': 'https://www.pichau.com.br/ssd-' + name, 'title': 'SSD ' + name,
                             'seller_id': 'Pichau', 'shipped_by': 'Pichau', 'price_cents': 36000,
                             'currency': 'BRL', 'available': True, 'payment_terms': 'PIX',
                             'observed_at': now.isoformat()} for name in ('kingston-1tb', 'crucial-1tb')]
                    Path('feed.json').write_text(json.dumps({'schema_version': 1, 'store': 'pichau', 'offers': rows}), encoding='utf-8')
                    settings = {'database_path': 'test.sqlite3', 'whatsapp_group_id': 'test@g.us',
                                'max_messages_per_run': 1,
                                'sources': {store: {'mode': 'disabled'} for store in ('kabum', 'amazon', 'magalu', 'mercadolivre')},
                                'discovery': {'stores': ['pichau'], 'categories': ['ssd'], 'max_products_per_run': 2}}
                    settings['sources']['pichau'] = {'mode': 'authorized_feed', 'feed_path': 'feed.json',
                                                       'authorization_reference': 'Test fixture'}
                    Path('settings.json').write_text(json.dumps(settings), encoding='utf-8')
                    initial = cycle()
                    with closing(connect('test.sqlite3')) as db:
                        for row in initial:
                            for days in (1, 2, 3):
                                record_price(db, 'pichau', row['offer']['product_id'], 49000, now - timedelta(days=days))
                    cycle()
                    failed = False
                    def checkpoint(connection):
                        nonlocal failed
                        states = {row[0] for row in connection.execute('SELECT state FROM dispatches')}
                        target = 'sending' if failure == 'before_send' else 'sent'
                        if target in states and not failed:
                            failed = True
                            raise RuntimeError('temporary checkpoint failure')
                    with patch('services.runner.publish', return_value='confirmed-id') as publish:
                        delivered = cycle(send=True, queued_only=True, checkpoint=checkpoint)
                        self.assertTrue(failed)
                        with closing(connect('test.sqlite3')) as db:
                            states = dict(db.execute('SELECT entry_id,state FROM pending_offers'))
                            if failure == 'before_send':
                                # First candidate did not reach WhatsApp and remains retryable;
                                # the second can still be delivered within this run's limit.
                                self.assertEqual(states[delivered[0]['id']], 'pending')
                                self.assertIn('send_error', delivered[0])
                                self.assertNotIn('persistence_error', delivered[0])
                                self.assertEqual(delivered[1]['send_status'], 'sent')
                            else:
                                self.assertEqual(states[delivered[0]['id']], 'sent')
                                self.assertEqual(delivered[0]['send_status'], 'sent')
                                self.assertIn('persistence_error', delivered[0])
                                self.assertNotIn('send_error', delivered[0])
                                self.assertTrue(delivered[1]['send_status'].startswith('queued:'))
                                self.assertEqual(states[delivered[1]['id']], 'pending')
                            self.assertEqual(db.execute('SELECT COUNT(*) FROM publications').fetchone()[0], 1)
                        publish.assert_called_once()
                finally:
                    os.chdir(previous)

    def test_expired_candidate_is_not_delivered(self):
        with closing(connect(':memory:')) as db:
            ensure_outbox(db)
            now = datetime.now(timezone.utc)
            offer = Offer('kabum', 'cpu', 'Processador Ryzen', 'KaBuM!', 36000,
                          None, 'PIX', True, 'https://www.kabum.com.br/produto/1')
            enqueue(db, {'store': 'kabum', 'id': 'cpu'}, offer, now - timedelta(minutes=31))
            self.assertEqual(pending(db, now), [])
            self.assertEqual(db.execute('SELECT state FROM pending_offers').fetchone()[0], 'expired')

    def test_publish_uses_collected_candidate_even_after_round_robin_moves_on(self):
        for price_changed in (False, True):
            with self.subTest(price_changed=price_changed), tempfile.TemporaryDirectory() as folder:
                previous = Path.cwd()
                os.chdir(folder)
                try:
                    now = datetime.now(timezone.utc)
                    rows = [{'url': 'https://www.pichau.com.br/ssd-' + name, 'title': 'SSD ' + name,
                             'seller_id': 'Pichau', 'shipped_by': 'Pichau', 'price_cents': 36000,
                             'currency': 'BRL', 'available': True, 'payment_terms': 'PIX',
                             'observed_at': now.isoformat()} for name in ('kingston-1tb', 'crucial-1tb')]
                    def write_feed():
                        Path('feed.json').write_text(json.dumps({'schema_version': 1, 'store': 'pichau', 'offers': rows}), encoding='utf-8')
                    write_feed()
                    settings = {'database_path': 'test.sqlite3', 'whatsapp_group_id': 'test@g.us',
                                'sources': {store: {'mode': 'disabled'} for store in ('kabum', 'amazon', 'magalu', 'mercadolivre')},
                                'discovery': {'stores': ['pichau'], 'categories': ['ssd'], 'max_products_per_run': 1}}
                    settings['sources']['pichau'] = {'mode': 'authorized_feed', 'feed_path': 'feed.json',
                                                       'authorization_reference': 'Test fixture'}
                    Path('settings.json').write_text(json.dumps(settings), encoding='utf-8')
                    with patch('services.runner.publish', return_value='confirmed-id') as publish:
                        first = cycle()[0]
                        with closing(connect('test.sqlite3')) as db:
                            for days in (1, 2, 3):
                                record_price(db, 'pichau', first['offer']['product_id'], 49000, now - timedelta(days=days))
                            db.execute("UPDATE tracked_products SET last_checked=? WHERE id<>?", (now.isoformat(), first['id']))
                            db.execute("UPDATE tracked_products SET last_checked='' WHERE id=?", (first['id'],))
                            db.commit()
                        collected = cycle()
                        self.assertEqual(collected[0]['id'], first['id'])
                        self.assertEqual(collected[0]['decision']['status'], 'approved')
                        if price_changed:
                            for row in rows:
                                if row['url'] == first['url']:
                                    row['price_cents'] = 39000
                            write_feed()
                        delivered = cycle(send=True, queued_only=True)
                        self.assertEqual(delivered[0]['id'], first['id'])
                        if price_changed:
                            publish.assert_not_called()
                            self.assertEqual(delivered[0]['status'], 'stale')
                        else:
                            publish.assert_called_once()
                            self.assertEqual(delivered[0]['send_status'], 'sent')
                            self.assertIn(first['url'], publish.call_args.args[0])
                finally:
                    os.chdir(previous)

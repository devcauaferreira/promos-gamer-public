import base64
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from services.cloud import CloudState, project_url
from publishers.whatsapp import validate_remote_bridge
from services.runner import dispatch
from database.models import Offer, connect
from config import Config
from datetime import datetime, timezone, timedelta
from services.price_history import record_price


class CloudTests(unittest.TestCase):
    def test_project_url_requires_https_without_credentials_or_query(self):
        for url in ('http://abc.supabase.co', 'https://abc.supabase.co?token=secret', 'https://user:pass@abc.supabase.co', 'https://example.com'):
            with patch('services.cloud.secret', return_value=url), self.assertRaises(ValueError):
                project_url()
        with patch('services.cloud.secret', return_value='https://abc.supabase.co'):
            self.assertEqual(project_url(),'https://abc.supabase.co')

    def test_checkpoint_version_and_restore(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'state.sqlite3'
            state = CloudState(path)
            with patch('services.cloud.cloud_request', return_value={'version':0,'payload':None}):
                state.restore()
            db = sqlite3.connect(path)
            try:
                db.execute('create table data (value text)')
                db.execute("insert into data values ('persisted')")
                with patch('services.cloud.cloud_request', return_value={'version':1}) as request:
                    state.checkpoint(db)
                    payload = request.call_args.args[2]['payload']
                    self.assertEqual(state.version,1)
                    self.assertTrue(base64.b64decode(payload).startswith(b'SQLite format 3\x00'))
            finally:
                db.close()
            other = CloudState(Path(folder) / 'restored.sqlite3')
            with patch('services.cloud.cloud_request', return_value={'version':1,'payload':payload}):
                other.restore()
            with closing(sqlite3.connect(other.path)) as restored:
                self.assertEqual(restored.execute('select value from data').fetchone()[0],'persisted')

    def test_failed_remote_reservation_prevents_whatsapp_send(self):
        db = connect(':memory:')
        try:
            db.execute('create table dispatches(store text, product_id text, channel text,state text,message_id text,updated_at text,primary key(store,product_id,channel))')
            now = datetime.now(timezone.utc)
            offer = Offer('kabum','cpu','Processador Ryzen','KaBuM!',38000,None,'PIX',True,'https://www.kabum.com.br/produto/1', shipped_by='KaBuM!')
            config = Config(trusted_sellers=frozenset({('kabum','KaBuM!')}))
            for day in (1,2,3):
                record_price(db,'kabum','cpu',49000,now-timedelta(days=day))
            with patch('services.runner.publish') as publish:
                def checkpoint(connection):
                    raise RuntimeError('State unavailable')
                with self.assertRaises(RuntimeError):
                    dispatch(db,offer,'message',config,'test@g.us',checkpoint=checkpoint)
                publish.assert_not_called()
        finally:
            db.close()

    def test_cloud_cannot_use_local_whatsapp_bridge(self):
        for url in ('http://127.0.0.1:8787', 'https://localhost:8787', ''):
            with patch('publishers.whatsapp.secret', return_value=url), self.assertRaises(ValueError):
                validate_remote_bridge()

    def test_runner_bridge_requires_ready_saved_session_and_target_group(self):
        import io
        import json
        from publishers.whatsapp import validate_publish_bridge
        with patch.dict('os.environ', {'GITHUB_ACTIONS':'true','WHATSAPP_RUNNER_BRIDGE':'true'}), patch('publishers.whatsapp.bridge_token',return_value='x'*32):
            for state in ({'ready':True,'group_found':True,'session_saved':True},
                          {'ready':True,'group_found':True,'session_saved':False},
                          {'ready':True,'group_found':False,'session_saved':True}):
                with patch('publishers.whatsapp.urlopen',return_value=io.BytesIO(json.dumps(state).encode())):
                    if all(state.values()):
                        self.assertEqual(validate_publish_bridge(),'http://127.0.0.1:8787')
                    else:
                        with self.assertRaises(ValueError): validate_publish_bridge()

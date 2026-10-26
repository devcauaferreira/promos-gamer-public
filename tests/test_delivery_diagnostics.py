import io
import json
import os
import tempfile
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from config import Config
from database.models import Offer, connect
from publishers.whatsapp import WhatsAppDeliveryError, publish
from whatsapp_cloud_job import run, send_media_test_once


MEDIA_TEST_MESSAGE = ('🧪 Teste técnico do Promos Gamer: validação de envio com foto pelo GitHub Actions. '
                      'Não é uma promoção.')
PHOTO = 'https://images.kabum.com.br/produtos/fotos/320799/photo.jpg'


@contextmanager
def isolated_workspace():
    previous = Path.cwd()
    with tempfile.TemporaryDirectory() as folder:
        os.chdir(folder)
        try:
            Path('settings.json').write_text(json.dumps({'whatsapp_group_id': 'test@g.us'}), encoding='utf-8')
            Path('products.json').write_text(json.dumps([{'store': 'kabum', 'id': 'kabum-320799',
                                                         'enabled': True}]), encoding='utf-8')
            yield Config(database_path=Path('state.sqlite3'))
        finally:
            os.chdir(previous)


class DeliveryDiagnosticsTests(unittest.TestCase):
    @patch('publishers.whatsapp.runner_bridge', return_value=True)
    @patch('publishers.whatsapp.bridge_token', return_value='x' * 32)
    @patch('urllib.request.build_opener')
    def test_bridge_http_error_exposes_only_allowed_error_code(self, opener, token, runner):
        for received, expected in (('confirmation_missing', 'whatsapp_confirmation_missing'),
                                   ('private-response-token', 'whatsapp_bridge_http_error')):
            with self.subTest(received=received):
                body = io.BytesIO(json.dumps({'error_code': received,
                                             'error': 'PRIVATE account data and token'}).encode())
                opener.return_value.open.side_effect = HTTPError(
                    'http://127.0.0.1:8787/send', 500, 'PRIVATE error', {}, body)
                with self.assertRaises(WhatsAppDeliveryError) as raised:
                    publish('Explicit test', 'test@g.us')
                self.assertEqual(raised.exception.code, expected)
                self.assertEqual(str(raised.exception), expected)
                self.assertNotIn('PRIVATE', str(raised.exception))
                self.assertNotIn('private-response-token', str(raised.exception))

    @patch('publishers.whatsapp.runner_bridge', return_value=True)
    @patch('publishers.whatsapp.bridge_token', return_value='x' * 32)
    @patch('publishers.whatsapp.product_image', return_value=None)
    @patch('urllib.request.build_opener')
    def test_required_photo_failure_happens_before_http_send(self, opener, photo, token, runner):
        with self.assertRaisesRegex(ValueError, 'Foto indisponível antes do envio'):
            publish('Explicit test', 'test@g.us', image_url=PHOTO, require_image=True)
        photo.assert_called_once_with(PHOTO)
        opener.assert_not_called()

    def media_offer(self):
        return Offer('kabum', 'kabum-320799', 'Processador AMD Ryzen 5 5500', 'KaBuM!',
                     59999, None, 'À vista no PIX', True,
                     'https://www.kabum.com.br/produto/320799/cpu',
                     shipped_by='KaBuM!', image_url=PHOTO)

    @patch.dict('os.environ', {'GITHUB_RUN_ID': '1234'})
    @patch('services.cloud.CloudState')
    @patch('collectors.registry.LazyBrowser')
    @patch('collectors.registry.build_sources')
    @patch('publishers.whatsapp.publish', return_value='photo-confirmed')
    def test_media_test_uses_exact_approved_caption_and_sends_only_once(self, publish_mock, sources,
                                                                     browser, state):
        source = Mock()
        source.collect.return_value = self.media_offer()
        sources.return_value = {'kabum': source}
        with isolated_workspace() as config:
            send_media_test_once(config)
            with patch.dict('os.environ', {'GITHUB_RUN_ID': '5678'}):
                send_media_test_once(config)
            publish_mock.assert_called_once_with(MEDIA_TEST_MESSAGE, 'test@g.us',
                                                 image_url=PHOTO, require_image=True)
            with closing(connect(config.database_path)) as db:
                self.assertEqual(db.execute('SELECT state,run_id,message_id FROM whatsapp_media_tests').fetchall(),
                                 [('confirmed', '1234', 'photo-confirmed')])
                self.assertEqual(db.execute('SELECT COUNT(*) FROM publications').fetchone()[0], 0)
            self.assertEqual(state.return_value.checkpoint.call_count, 2)
            source.collect.assert_called_once()
            browser.return_value.close.assert_called_once()

    @patch.dict('os.environ', {'GITHUB_RUN_ID': '1234'})
    @patch('services.cloud.CloudState')
    @patch('collectors.registry.LazyBrowser')
    @patch('collectors.registry.build_sources')
    @patch('publishers.whatsapp.publish', side_effect=WhatsAppDeliveryError('whatsapp_confirmation_missing'))
    def test_uncertain_media_test_is_persisted_and_not_repeated(self, publish_mock, sources, browser, state):
        source = Mock()
        source.collect.return_value = self.media_offer()
        sources.return_value = {'kabum': source}
        with isolated_workspace() as config:
            with self.assertRaises(WhatsAppDeliveryError):
                send_media_test_once(config)
            with patch.dict('os.environ', {'GITHUB_RUN_ID': '5678'}):
                send_media_test_once(config)
            with closing(connect(config.database_path)) as db:
                self.assertEqual(db.execute('SELECT state,message_id FROM whatsapp_media_tests').fetchone(),
                                 ('uncertain', None))
                self.assertEqual(db.execute('SELECT COUNT(*) FROM publications').fetchone()[0], 0)
            publish_mock.assert_called_once()
            self.assertEqual(state.return_value.checkpoint.call_count, 2)
            source.collect.assert_called_once()

    @patch.dict('os.environ', {'GITHUB_ACTIONS': 'true'})
    @patch('whatsapp_cloud_job.configure')
    @patch('whatsapp_cloud_job.subprocess.Popen')
    def test_verify_mode_cannot_launch_media_test(self, popen, configure):
        with self.assertRaisesRegex(ValueError, 'Verificação não permite envio'):
            run(verify_only=True, send_media_test=True)
        popen.assert_not_called()
        configure.assert_not_called()


if __name__ == '__main__':
    unittest.main()

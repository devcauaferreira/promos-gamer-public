import io
import json
import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from whatsapp_cloud_job import run
from whatsapp_cloud_job import send_test_once
from config import Config


class WhatsAppJobTests(unittest.TestCase):
    @patch.dict('os.environ', {'GITHUB_ACTIONS':'true'})
    @patch('whatsapp_cloud_job.configure')
    @patch('whatsapp_cloud_job.subprocess.Popen')
    @patch('whatsapp_cloud_job.subprocess.run')
    @patch('whatsapp_cloud_job.urlopen')
    def test_connection_job_never_runs_publisher(self, urlopen, execute, popen, configure):
        process = Mock(returncode=0)
        process.poll.return_value = None
        popen.return_value = process
        urlopen.return_value = io.BytesIO(json.dumps({'ready':True,'session_saved':True,'group_found':True}).encode())
        run(connect_only=True)
        execute.assert_not_called()
        self.assertEqual(popen.call_args.kwargs['env']['WHATSAPP_ALLOW_QR'],'true')
        process.terminate.assert_called_once()
        process.wait.assert_called_once()

    @patch.dict('os.environ', {'GITHUB_ACTIONS':'true'})
    @patch('whatsapp_cloud_job.configure')
    @patch('whatsapp_cloud_job.subprocess.Popen')
    @patch('whatsapp_cloud_job.subprocess.run')
    @patch('whatsapp_cloud_job.urlopen')
    def test_monitor_waits_for_health_then_uses_same_private_bridge(self, urlopen, execute, popen, configure):
        process = Mock(returncode=0)
        process.poll.return_value = None
        popen.return_value = process
        urlopen.return_value = io.BytesIO(json.dumps({'ready':True,'session_saved':True,'group_found':True}).encode())
        run(limit=5)
        self.assertIn('--send',execute.call_args.args[0])
        env = execute.call_args.kwargs['env']
        self.assertEqual(env['WHATSAPP_RUNNER_BRIDGE'],'true')
        self.assertEqual(env['WHATSAPP_ALLOW_QR'],'false')
        self.assertEqual(env['WHATSAPP_BRIDGE_TOKEN'],popen.call_args.kwargs['env']['WHATSAPP_BRIDGE_TOKEN'])
        process.terminate.assert_called_once()

    @patch.dict('os.environ', {'GITHUB_ACTIONS':'false'})
    def test_refuses_to_run_outside_actions(self):
        with self.assertRaises(ValueError):
            run()

    @patch.dict('os.environ', {'GITHUB_RUN_ID':'1234'})
    @patch('services.cloud.CloudState')
    @patch('publishers.whatsapp.publish', side_effect=TimeoutError('uncertain'))
    def test_uncertain_test_message_is_not_repeated(self, publish, state):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as folder:
            os.chdir(folder)
            try:
                Path('settings.json').write_text(json.dumps({'whatsapp_group_id':'test@g.us'}))
                config = Config(database_path=Path('test.sqlite3'))
                with self.assertRaises(TimeoutError): send_test_once(config)
                with patch.dict('os.environ', {'GITHUB_RUN_ID':'5678'}), patch('publishers.whatsapp.bridge_token',return_value='x'*32), patch('whatsapp_cloud_job.urlopen',return_value=io.BytesIO(b'{"found":false,"confirmed":false}')):
                    with self.assertRaises(RuntimeError): send_test_once(config)
                publish.assert_called_once()
                state.return_value.checkpoint.assert_called_once()
            finally: os.chdir(previous)

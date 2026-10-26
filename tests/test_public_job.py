import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from services.public_job import run_job, safe_failure_code, safe_summary


class PublicJobTests(unittest.TestCase):
    def test_child_output_is_private_and_failure_propagates(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as folder:
            os.chdir(folder)
            try:
                output = io.StringIO()
                def child(command, stdout, stderr):
                    stdout.write(b"private-token-and-group-details")
                    return Mock(returncode=1)
                with patch("services.public_job.subprocess.run", side_effect=child), contextlib.redirect_stdout(output):
                    self.assertEqual(run_job("publish", 5), 1)
                self.assertNotIn("private-token", output.getvalue())
                self.assertIn("falhou", output.getvalue())
                self.assertIn("child_failed", output.getvalue())
                self.assertEqual(Path("reports/cloud-job-private.log").read_bytes(), b"private-token-and-group-details")
            finally:
                os.chdir(previous)

    def test_safe_failure_code_classifies_only_allowlisted_markers(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "private.log"
            log.write_text("RuntimeError: Função Supabase retornou HTTP 409; private-token=secret", encoding="utf-8")
            self.assertEqual(safe_failure_code(log), "supabase_state_conflict")
            log.write_text("Traceback (most recent call last): RuntimeError: arbitrary private token content", encoding="utf-8")
            self.assertEqual(safe_failure_code(log), "child_exception")
            log.write_text("SessÃ£o da nuvem precisa de autorizaÃ§Ã£o.", encoding="utf-8")
            self.assertEqual(safe_failure_code(log), "whatsapp_reauthorization_required")
            log.write_text("Bridge startup diagnostic: whatsapp_browser_launch_failed\nprivate path C:/secret", encoding="utf-8")
            self.assertEqual(safe_failure_code(log), "whatsapp_browser_launch_failed")
            log.write_text("Bridge startup diagnostic: whatsapp_session_http_403 Bearer secret", encoding="utf-8")
            self.assertEqual(safe_failure_code(log), "whatsapp_session_http_403")
            log.write_text("Ponte encerrou. Bridge startup diagnostic: whatsapp_session_http_418 private", encoding="utf-8")
            self.assertEqual(safe_failure_code(log), "whatsapp_bridge_stopped")
            self.assertEqual(safe_failure_code(Path(folder) / "missing.log"), "child_failed")

    def test_collect_never_requests_sending(self):
        with patch("services.public_job.Path.mkdir"), patch("services.public_job.Path.open"), patch("services.public_job.subprocess.run", return_value=Mock(returncode=0)) as run:
            self.assertEqual(run_job("collect", 20), 0)
            self.assertIn("--check-candidates", run.call_args.args[0])
            self.assertNotIn("--send", run.call_args.args[0])

    def test_invalid_task_rejected_before_subprocess(self):
        with patch("services.public_job.subprocess.run") as run:
            with self.assertRaises(ValueError):
                run_job("publish", send_test=True)
            run.assert_not_called()
            with self.assertRaises(ValueError):
                run_job("connect", send_test=True, send_preview=True)
            run.assert_not_called()

    def test_safe_summary_omits_private_offer_details(self):
        import json
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as folder:
            os.chdir(folder)
            try:
                Path("reports").mkdir()
                Path("reports/sources.json").write_text(json.dumps([
                    {"store": "kabum", "state": "operational", "error": "secret-value"}]))
                Path("reports/latest.json").write_text(json.dumps([
                    {"url": "https://secret.example/item", "decision": {"status": "pending_review",
                     "reasons": ["Histórico insuficiente", "secret-value"]}}]))
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    safe_summary()
                self.assertIn("sem histórico anterior: 1", output.getvalue())
                self.assertNotIn("secret", output.getvalue())
            finally:
                os.chdir(previous)

    def test_publish_failure_reports_new_delivery_counts_but_not_old_collect_report(self):
        import json
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as folder:
            os.chdir(folder)
            try:
                Path('reports').mkdir()
                Path('reports/sources.json').write_text('[]')
                Path('reports/latest.json').write_text(json.dumps([{'send_status': 'sent'}] * 50))
                output = io.StringIO()
                with patch('services.public_job.subprocess.run', return_value=Mock(returncode=1)), contextlib.redirect_stdout(output):
                    self.assertEqual(run_job('publish'), 1)
                self.assertNotIn('Envios confirmados:', output.getvalue())
                def child(command, stdout, stderr):
                    Path('reports/latest.json').write_text(json.dumps([
                        {'send_status': 'sent'}, {'send_error': 'private-token-detail'}]))
                    return Mock(returncode=1)
                output = io.StringIO()
                with patch('services.public_job.subprocess.run', side_effect=child), contextlib.redirect_stdout(output):
                    self.assertEqual(run_job('publish'), 1)
                self.assertIn('Envios confirmados: 1; erros: 1', output.getvalue())
                self.assertNotIn('private-token-detail', output.getvalue())
            finally:
                os.chdir(previous)

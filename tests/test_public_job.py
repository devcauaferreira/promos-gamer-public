import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from services.public_job import run_job


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
                self.assertEqual(Path("reports/cloud-job-private.log").read_bytes(), b"private-token-and-group-details")
            finally:
                os.chdir(previous)

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

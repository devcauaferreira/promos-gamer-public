import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from collectors.registry import LazyBrowser
from scripts.setup_runner_browser import BROWSER_NAMES, setup_runner_browser


class RunnerBrowserTests(unittest.TestCase):
    def fixture(self, folder):
        browser = Path(folder) / 'google-chrome'
        browser.write_bytes(b'browser placeholder')
        target = Path(folder) / 'github-env'
        target.write_text('EXISTING=value\n', encoding='utf-8')
        return browser, target, {'GITHUB_ACTIONS': 'true', 'GITHUB_ENV': str(target)}

    def test_preinstalled_browser_is_verified_and_only_expected_keys_are_appended(self):
        with tempfile.TemporaryDirectory() as folder:
            browser, target, env = self.fixture(folder)
            which = Mock(return_value=str(browser))
            run = Mock(return_value=Mock(returncode=0, stdout='Google Chrome 142.0.7444.59\n'))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                selected = setup_runner_browser(env, which=which, run=run)
            expected = str(browser.resolve())
            self.assertEqual(selected, expected)
            run.assert_called_once_with([expected, '--version'], capture_output=True, text=True,
                                        timeout=10, check=False)
            self.assertNotIn('shell', run.call_args.kwargs)
            self.assertEqual(target.read_text(encoding='utf-8').splitlines(), [
                'EXISTING=value', 'PLAYWRIGHT_BROWSER_PATH=' + expected,
                'WHATSAPP_BROWSER_PATH=' + expected, 'PUPPETEER_SKIP_DOWNLOAD=true'])
            self.assertNotIn(expected, output.getvalue())

    def test_local_execution_is_rejected_without_search_or_write(self):
        with tempfile.TemporaryDirectory() as folder:
            _, target, env = self.fixture(folder)
            which, run = Mock(), Mock()
            env['GITHUB_ACTIONS'] = 'false'
            with self.assertRaises(ValueError):
                setup_runner_browser(env, which=which, run=run)
            which.assert_not_called()
            run.assert_not_called()
            self.assertEqual(target.read_text(encoding='utf-8'), 'EXISTING=value\n')

    def test_missing_browser_fails_without_download_or_environment_change(self):
        with tempfile.TemporaryDirectory() as folder:
            _, target, env = self.fixture(folder)
            which, run = Mock(return_value=None), Mock()
            with self.assertRaises(RuntimeError):
                setup_runner_browser(env, which=which, run=run)
            self.assertEqual([call.args[0] for call in which.call_args_list], list(BROWSER_NAMES))
            run.assert_not_called()
            self.assertEqual(target.read_text(encoding='utf-8'), 'EXISTING=value\n')

    def test_failed_or_unknown_version_does_not_write_environment(self):
        for result in (Mock(returncode=1, stdout='Google Chrome 142.0.0.0'),
                       Mock(returncode=0, stdout='private-token-output'),
                       subprocess.TimeoutExpired(['browser', '--version'], 10)):
            with self.subTest(result=type(result).__name__), tempfile.TemporaryDirectory() as folder:
                browser, target, env = self.fixture(folder)
                run = Mock(side_effect=result) if isinstance(result, Exception) else Mock(return_value=result)
                with contextlib.redirect_stdout(io.StringIO()) as output, self.assertRaises(RuntimeError):
                    setup_runner_browser(env, which=Mock(return_value=str(browser)), run=run)
                self.assertNotIn('private-token-output', output.getvalue())
                self.assertEqual(target.read_text(encoding='utf-8'), 'EXISTING=value\n')

    def test_invalid_environment_or_browser_path_never_runs_or_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            browser, target, env = self.fixture(folder)
            for invalid in ('https://evil.example/browser', 'relative-browser', str(browser) + '\nINJECTED=value', str(Path(folder))):
                with self.subTest(browser=invalid):
                    run = Mock()
                    with self.assertRaises(ValueError):
                        setup_runner_browser(env, which=Mock(return_value=invalid), run=run)
                    run.assert_not_called()
            for invalid in ('https://evil.example/env', 'relative-env', str(target) + '\nINJECTED=value', folder):
                with self.subTest(env=invalid):
                    which, run = Mock(), Mock()
                    with self.assertRaises(ValueError):
                        setup_runner_browser(dict(env, GITHUB_ENV=invalid), which=which, run=run)
                    which.assert_not_called()
                    run.assert_not_called()
            self.assertEqual(target.read_text(encoding='utf-8'), 'EXISTING=value\n')

    def test_chromium_fallback_is_accepted_after_missing_chrome(self):
        with tempfile.TemporaryDirectory() as folder:
            browser, _, env = self.fixture(folder)
            which = Mock(side_effect=[None, None, str(browser)])
            run = Mock(return_value=Mock(returncode=0, stdout='Chromium 140.0.7339.207 built on Debian\n'))
            self.assertEqual(setup_runner_browser(env, which=which, run=run), str(browser.resolve()))
            self.assertEqual(which.call_count, 3)

    def test_lazy_browser_uses_selected_executable_and_keeps_local_default(self):
        for selected in ('/usr/bin/google-chrome', ''):
            with self.subTest(selected=selected), patch.dict(os.environ, {'PLAYWRIGHT_BROWSER_PATH': selected}), patch('playwright.sync_api.sync_playwright') as playwright:
                manager = playwright.return_value.start.return_value
                browser = LazyBrowser(visible=False)
                browser.new_page(locale='pt-BR')
                expected = {'headless': True}
                if selected:
                    expected['executable_path'] = selected
                manager.chromium.launch.assert_called_once_with(**expected)
                manager.chromium.launch.return_value.new_page.assert_called_once_with(locale='pt-BR')

import io
import json
import unittest
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock

from scripts.watchdog_monitor import recover_monitor


ACTIVE = ('queued', 'pending', 'in_progress', 'waiting', 'requested')


def response(payload=None, status=200, raw=None):
    stream = io.BytesIO(raw if raw is not None else json.dumps(payload).encode())
    stream.status = status
    return stream


class WatchdogTests(unittest.TestCase):
    def env(self, **changes):
        return dict({'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'example/project',
                     'GITHUB_RUN_ID': '123', 'GH_TOKEN': 'test-token',
                     'GITHUB_API_URL': 'https://api.github.com',
                     'PROMOS_CLOUD_ENABLED': 'true', 'PROMOS_CHAIN_ENABLED': 'true'}, **changes)

    def methods(self, opener):
        return [call.args[0].get_method() for call in opener.open.call_args_list]

    def test_disabled_monitor_or_chain_never_uses_http(self):
        for changes in ({'PROMOS_CLOUD_ENABLED': 'false'}, {'PROMOS_CHAIN_ENABLED': 'false'},
                        {'PROMOS_CLOUD_ENABLED': ''}, {'PROMOS_CHAIN_ENABLED': ''}):
            with self.subTest(changes=changes):
                opener = Mock()
                self.assertFalse(recover_monitor(self.env(**changes), opener=opener))
                opener.open.assert_not_called()

    def test_each_active_state_in_production_or_connection_prevents_dispatch(self):
        for workflow in ('promos.yml', 'whatsapp-connect.yml'):
            for state in ACTIVE:
                with self.subTest(workflow=workflow, state=state):
                    opener = Mock()
                    def read(request, timeout):
                        parsed = urlparse(request.full_url)
                        requested = parse_qs(parsed.query)['status'][0]
                        runs = ([{'id': 456, 'status': state}]
                                if '/workflows/' + workflow + '/runs' in parsed.path and requested == state else [])
                        return response({'workflow_runs': runs})
                    opener.open.side_effect = read
                    self.assertFalse(recover_monitor(self.env(), opener=opener))
                    self.assertTrue(opener.open.called)
                    self.assertNotIn('POST', self.methods(opener))

    def test_no_active_run_dispatches_main_self_chain_once(self):
        opener = Mock()
        def read(request, timeout):
            if request.get_method() == 'POST':
                return response(status=204)
            # The current watchdog must not prevent its own recovery check.
            return response({'workflow_runs': [{'id': 123, 'status': 'in_progress'}]})
        opener.open.side_effect = read
        self.assertTrue(recover_monitor(self.env(), opener=opener))
        self.assertEqual(self.methods(opener).count('GET'), len(ACTIVE) * 2)
        self.assertEqual(self.methods(opener).count('POST'), 1)
        requests = [call.args[0] for call in opener.open.call_args_list]
        for request in requests[:-1]:
            parsed = urlparse(request.full_url)
            self.assertEqual(parsed.hostname, 'api.github.com')
            self.assertEqual(parse_qs(parsed.query)['branch'], ['main'])
            self.assertEqual(parse_qs(parsed.query)['per_page'], ['100'])
        self.assertEqual(requests[-1].full_url,
                         'https://api.github.com/repos/example/project/actions/workflows/promos.yml/dispatches')
        payload = json.loads(requests[-1].data)
        self.assertEqual(payload['ref'], 'main')
        self.assertEqual(payload['inputs']['source'], 'self_chain')
        self.assertEqual(payload['inputs']['publish'], 'true')
        self.assertEqual(payload['inputs']['limit'], '20')

    def test_failed_get_does_not_dispatch(self):
        for error in (URLError('offline'), TimeoutError('timeout'),
                      HTTPError('https://api.github.com', 503, 'unavailable', {}, None)):
            with self.subTest(error=type(error).__name__):
                opener = Mock()
                opener.open.side_effect = error
                with self.assertRaises(RuntimeError):
                    recover_monitor(self.env(), opener=opener)
                self.assertEqual(self.methods(opener), ['GET'])

    def test_ambiguous_post_failure_is_not_retried(self):
        for error in (TimeoutError('result unknown'), URLError('connection lost'),
                      HTTPError('https://api.github.com', 503, 'unavailable', {}, None)):
            with self.subTest(error=type(error).__name__):
                opener = Mock()
                def read(request, timeout):
                    if request.get_method() == 'POST':
                        raise error
                    return response({'workflow_runs': []})
                opener.open.side_effect = read
                with self.assertRaises(RuntimeError):
                    recover_monitor(self.env(), opener=opener)
                self.assertEqual(self.methods(opener).count('POST'), 1)
                self.assertEqual(self.methods(opener).count('GET'), len(ACTIVE) * 2)

    def test_unconfirmed_post_is_not_success_or_retried(self):
        opener = Mock()
        opener.open.side_effect = lambda request, timeout: (
            response(status=200) if request.get_method() == 'POST' else response({'workflow_runs': []}))
        with self.assertRaises(RuntimeError):
            recover_monitor(self.env(), opener=opener)
        self.assertEqual(self.methods(opener).count('POST'), 1)

    def test_foreign_api_url_is_rejected_before_http(self):
        for api in ('https://evil.example', 'https://api.github.com.evil.example', 'http://api.github.com'):
            with self.subTest(api=api):
                opener = Mock()
                with self.assertRaises(ValueError):
                    recover_monitor(self.env(GITHUB_API_URL=api), opener=opener)
                opener.open.assert_not_called()

    def test_invalid_response_shape_never_dispatches(self):
        for payload in (None, [], {}, {'workflow_runs': None}, {'workflow_runs': {}}, {'workflow_runs': 'invalid'}):
            with self.subTest(payload=payload):
                opener = Mock()
                opener.open.return_value = response(payload)
                with self.assertRaises(RuntimeError):
                    recover_monitor(self.env(), opener=opener)
                self.assertEqual(self.methods(opener), ['GET'])

    def test_invalid_json_never_dispatches(self):
        opener = Mock()
        opener.open.return_value = response(raw=b'not-json')
        with self.assertRaises(RuntimeError):
            recover_monitor(self.env(), opener=opener)
        self.assertEqual(self.methods(opener), ['GET'])


if __name__ == '__main__':
    unittest.main()

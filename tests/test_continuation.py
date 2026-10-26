import io
import json
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError

from scripts.continue_monitor import continue_monitor


class Response(io.BytesIO):
    status = 204


class ContinuationTests(unittest.TestCase):
    def env(self):
        return {'PROMOS_CHAIN_ENABLED': 'true', 'GITHUB_ACTIONS': 'true',
                'GITHUB_REPOSITORY': 'example/promos', 'GH_TOKEN': 'temporary-token'}

    def test_disabled_does_not_dispatch(self):
        opener = Mock()
        self.assertFalse(continue_monitor({}, opener=opener))
        opener.open.assert_not_called()

    def test_successor_queued_before_waiting_and_interval_preserved(self):
        ticks = [1800000000.0]
        events = []
        opener = Mock()
        def open_request(request, timeout):
            events.append('dispatch')
            self.assertEqual(request.get_header('Authorization'), 'Bearer temporary-token')
            payload = json.loads(request.data)
            self.assertEqual(payload['inputs']['source'], 'self_chain')
            self.assertEqual(payload['inputs']['not_before'], '1800000320')
            return Response()
        def sleep(seconds):
            events.append('wait')
            ticks[0] += seconds
        opener.open.side_effect = open_request
        env = dict(self.env(), NEXT_SLOT='1800000020')
        self.assertTrue(continue_monitor(env, opener=opener, clock=lambda: ticks[0], sleep=sleep))
        self.assertEqual(events, ['dispatch', 'wait'])
        self.assertEqual(ticks[0], 1800000020)

    def test_denial_is_not_retried(self):
        opener = Mock()
        opener.open.side_effect = HTTPError('https://api.github.com', 403, 'Forbidden', {}, None)
        with self.assertRaisesRegex(RuntimeError, 'HTTP 403'):
            continue_monitor(self.env(), opener=opener, clock=lambda: 1800000000)
        self.assertEqual(opener.open.call_count, 1)

    def test_rejects_credential_destination_and_unbounded_wait(self):
        for change in ({'GITHUB_API_URL': 'https://evil.example'}, {'NEXT_SLOT': '1800001000'},
                       {'NEXT_SLOT': '$(invalid)'}, {'GITHUB_REPOSITORY': '../bad/path'}):
            opener = Mock()
            with self.assertRaises(ValueError):
                continue_monitor(dict(self.env(), **change), opener=opener, clock=lambda: 1800000000)
            opener.open.assert_not_called()

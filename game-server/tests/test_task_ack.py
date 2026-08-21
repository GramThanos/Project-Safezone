"""Tests for command acknowledgement waiting.

`tasks` pulls in the service runtime (redis, sqlalchemy, vdf), so these run
inside the game-server container and skip on a bare host.
"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

try:
    import tasks
    IMPORT_ERROR = None
except ImportError as exc:  # pragma: no cover - depends on the environment
    tasks = None
    IMPORT_ERROR = exc


@unittest.skipIf(tasks is None, f"game-server runtime deps not installed ({IMPORT_ERROR})")
class TestAwaitCommandAck(unittest.TestCase):
    def test_returns_ack_once_published(self):
        ack = json.dumps({'ok': True, 'detail': None})
        with mock.patch.object(tasks.cache, 'get_value', return_value=ack):
            self.assertEqual(tasks._await_command_ack('abc', timeout=1),
                             {'ok': True, 'detail': None})

    def test_returns_failure_ack(self):
        ack = json.dumps({'ok': False, 'detail': 'server not running'})
        with mock.patch.object(tasks.cache, 'get_value', return_value=ack):
            result = tasks._await_command_ack('abc', timeout=1)
        self.assertFalse(result['ok'])
        self.assertEqual(result['detail'], 'server not running')

    def test_times_out_when_no_manager_answers(self):
        """No ack means no manager wrote the command - never treat that as sent."""
        with mock.patch.object(tasks.cache, 'get_value', return_value=None):
            self.assertIsNone(
                tasks._await_command_ack('abc', timeout=0.2, poll_interval=0.05)
            )

    def test_polls_until_the_ack_appears(self):
        answers = [None, None, json.dumps({'ok': True, 'detail': None})]
        with mock.patch.object(tasks.cache, 'get_value', side_effect=answers) as get_value:
            result = tasks._await_command_ack('abc', timeout=5, poll_interval=0.01)
        self.assertEqual(result, {'ok': True, 'detail': None})
        self.assertEqual(get_value.call_count, 3)

    def test_malformed_ack_is_a_failure_not_a_crash(self):
        with mock.patch.object(tasks.cache, 'get_value', return_value='not json'):
            result = tasks._await_command_ack('abc', timeout=1)
        self.assertFalse(result['ok'])


if __name__ == '__main__':
    unittest.main()

"""Tests for stack deliveries: several inventory bundles in one give_reward task.

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


SERVER = {'id': 1, 'name': 'main'}


@unittest.skipIf(tasks is None, f"game-server runtime deps not installed ({IMPORT_ERROR})")
class TestStackDelivery(unittest.TestCase):
    def _run(self, data, results=None):
        """Run give_reward with every console line answered from ``results``."""
        sent = []
        answers = iter(results or [])

        def console(server, text):
            sent.append(text)
            return next(answers, (True, None))

        online = json.dumps(['Alice'])
        with mock.patch.object(tasks.servers, 'get', return_value=SERVER), \
                mock.patch.object(tasks.cache, 'get_value', return_value=online), \
                mock.patch.object(tasks, 'send_console', side_effect=console), \
                mock.patch.object(tasks.time, 'sleep'):
            ok = tasks.give_reward(data)
        return ok, sent

    def _items(self, *counts):
        return {'server_id': 1, 'username': 'Alice', 'kind': 'item', 'in_game_id': 'Base.Nails',
                'bundles': [{'ref': 10 + i, 'count': c} for i, c in enumerate(counts)]}

    def test_packs_bundles_into_few_lines(self):
        ok, sent = self._run(self._items(40, 40, 40))
        self.assertTrue(ok)
        self.assertEqual(sent, ['additem "Alice" "Base.Nails" 80',
                                'additem "Alice" "Base.Nails" 40'])

    def test_reports_every_bundle_delivered(self):
        data = self._items(5, 5)
        ok, _ = self._run(data)
        self.assertTrue(ok)
        self.assertEqual(data['delivered_refs'], [10, 11])

    def test_a_failed_line_hands_back_only_its_bundles(self):
        """The first line landed; the bundles in it must not come back as well."""
        data = self._items(60, 30, 50)
        ok, sent = self._run(data, results=[(True, None), (False, 'no response')])
        self.assertFalse(ok)
        self.assertEqual(len(sent), 2)
        self.assertEqual(data['delivered_refs'], [10, 11])

    def test_nothing_delivered_when_the_player_is_offline(self):
        data = self._items(5)
        with mock.patch.object(tasks.servers, 'get', return_value=SERVER), \
                mock.patch.object(tasks.cache, 'get_value', return_value='[]'), \
                mock.patch.object(tasks, 'send_console') as console:
            self.assertFalse(tasks.give_reward(data))
        console.assert_not_called()
        self.assertEqual(data['delivered_refs'], [])

    def test_invalid_bundles_deliver_nothing(self):
        data = self._items(5)
        data['bundles'].append({'ref': 10, 'count': 5})   # a duplicate
        ok, sent = self._run(data)
        self.assertFalse(ok)
        self.assertEqual(sent, [])
        self.assertEqual(data['delivered_refs'], [])

    def test_a_usable_runs_once_per_bundle(self):
        data = {'server_id': 1, 'username': 'Alice', 'kind': 'usable',
                'commands': 'addxp "{{USERNAME}}" Strength=1\nsleep 1',
                'bundles': [{'ref': 1}, {'ref': 2}, {'ref': 3}]}
        ok, sent = self._run(data, results=[(True, None), (False, 'no response')])
        self.assertFalse(ok)
        self.assertEqual(sent, ['addxp "Alice" Strength=1'] * 2)
        self.assertEqual(data['delivered_refs'], [1])

    def test_a_single_reward_is_unchanged(self):
        """The admin Give path sends no bundles and gets no delivered_refs."""
        data = {'server_id': 1, 'username': 'Alice', 'kind': 'item',
                'in_game_id': 'Base.Axe', 'count': 2}
        ok, sent = self._run(data)
        self.assertTrue(ok)
        self.assertEqual(sent, ['additem "Alice" "Base.Axe" 2'])
        self.assertNotIn('delivered_refs', data)


if __name__ == '__main__':
    unittest.main()

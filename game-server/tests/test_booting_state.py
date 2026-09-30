"""Tests for the "booting" live state.

A live process is not a joinable server: Project Zomboid spends minutes loading
its world, and players seeing "running" through all of it could not tell a
server that is up from one still coming up. The manager reports "booting" until
the server has answered a `players` query, which is the same proof of life that
arms the idle timeout.

Same import dance as `test_crash_loop.py`.
"""
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

try:
    import pwd  # noqa: F401
except ImportError:
    sys.modules['pwd'] = types.ModuleType('pwd')

try:
    import manager_game
    IMPORT_ERROR = None
except Exception as e:  # pragma: no cover - depends on the host
    manager_game = None
    IMPORT_ERROR = e


@unittest.skipIf(manager_game is None,
                 f"game-server runtime deps not installed ({IMPORT_ERROR})")
class TestBootingState(unittest.TestCase):

    def setUp(self):
        for target, attr, value in (
            (manager_game.GameManager, 'log', lambda self, message: None),
            (manager_game.GameManager, '_is_game_server_running', lambda self: True),
        ):
            patcher = mock.patch.object(target, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.set_value = mock.patch.object(manager_game.cache, 'set_value').start()
        self.emit = mock.patch.object(manager_game.events, 'emit').start()
        self.addCleanup(mock.patch.stopall)

        self.manager = manager_game.GameManager(
            1, 'test-server', [16261], initial_state='running'
        )

    def _published(self):
        self.manager._publish_live_state()
        return self.set_value.call_args[0][1]

    def test_a_live_process_that_has_not_answered_is_booting(self):
        self.manager._roster_ready = False
        self.assertEqual(self._published(), 'booting')

    def test_it_is_running_once_the_roster_has_answered(self):
        self.manager._roster_ready = True
        self.assertEqual(self._published(), 'running')

    def test_booting_is_not_announced_but_becoming_joinable_is(self):
        self.manager._published_state = 'sleeping'
        self.manager._roster_ready = False
        self._published()
        self.emit.assert_not_called()

        self.manager._roster_ready = True
        self._published()
        self.emit.assert_called_once()
        self.assertEqual(self.emit.call_args.kwargs['state'], 'running')
        self.assertEqual(self.emit.call_args.kwargs['previous'], 'sleeping')


if __name__ == '__main__':
    unittest.main()

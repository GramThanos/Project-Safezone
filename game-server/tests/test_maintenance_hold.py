"""Tests for the maintenance hold and the update's refusal to run under a server.

The hold is the whole safety story of maintenance: files every server shares
are replaced while it is in place, so a server must not run the game or listen
for a wake while held - and must come back to what it was doing afterwards
without the stop being mistaken for a crash.

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
    import vdf  # noqa: F401
except ImportError:
    sys.modules['vdf'] = types.ModuleType('vdf')

try:
    import manager_game
    import tasks
    IMPORT_ERROR = None
except Exception as e:  # pragma: no cover - depends on the host
    manager_game = tasks = None
    IMPORT_ERROR = e


@unittest.skipIf(manager_game is None,
                 f"game-server runtime deps not installed ({IMPORT_ERROR})")
class TestMaintenanceHold(unittest.TestCase):

    def setUp(self):
        mock.patch.object(manager_game.GameManager, 'log', lambda self, message: None).start()
        self.set_value = mock.patch.object(manager_game.cache, 'set_value').start()
        self.emit = mock.patch.object(manager_game.events, 'emit').start()
        self.addCleanup(mock.patch.stopall)
        self.manager = manager_game.GameManager(1, 'test-server', [16261],
                                                initial_state='running')

    def _one_pass(self, held, game_alive=True, wake_alive=False):
        """Run exactly one reconcile pass with the hold as given."""
        manager = self.manager
        manager.commands_listener = lambda: None
        manager._read_maintenance_hold = lambda: held
        manager._is_game_server_running = lambda: game_alive
        manager._is_onwake_running = lambda: wake_alive
        manager.manage_server_process = mock.Mock()
        manager.manage_onwake = mock.Mock()
        manager._stop_event.wait = lambda timeout=None: manager._stop_event.set()
        manager.run()
        manager._stop_event.clear()

    def test_a_held_server_is_stopped_but_keeps_its_goal(self):
        self._one_pass(held=True, game_alive=True, wake_alive=True)
        self.manager.manage_server_process.assert_called_once_with(start=False)
        self.manager.manage_onwake.assert_called_once_with(start=False)
        self.assertEqual(self.manager.state, 'running')

    def test_a_held_server_is_not_relaunched(self):
        self._one_pass(held=True, game_alive=False)
        for call in self.manager.manage_server_process.call_args_list:
            self.assertNotEqual(call, mock.call(start=True))

    def test_it_reports_maintenance_and_announces_nothing(self):
        self.manager._published_state = 'sleeping'
        self.manager._held = True
        self.manager._is_game_server_running = lambda: False
        self.manager._publish_live_state()
        self.assertEqual(self.set_value.call_args[0][1], 'maintenance')
        self.emit.assert_not_called()
        # Coming back to the state it had before is not news either.
        self.assertEqual(self.manager._published_state, 'sleeping')

    def test_launching_is_refused_while_held(self):
        self.manager._held = True
        self.manager._is_game_server_running = lambda: False
        with mock.patch.object(manager_game.subprocess, 'Popen') as popen:
            self.manager.manage_server_process(start=True)
        popen.assert_not_called()

    def test_the_held_stop_is_not_counted_as_a_crash(self):
        self.manager._held = True
        self._one_pass(held=False, game_alive=False)
        self.assertFalse(self.manager._held)
        # Relaunched straight away, with no crash history to back off from.
        self.manager.manage_server_process.assert_called_once_with(start=True)
        self.assertEqual(len(self.manager._restart_times), 1)


@unittest.skipIf(tasks is None, f"game-server runtime deps not installed ({IMPORT_ERROR})")
class TestUpdateRefusesLiveServers(unittest.TestCase):

    SERVERS = [{'id': 1, 'name': 'alpha'}, {'id': 2, 'name': 'beta'}]

    def setUp(self):
        mock.patch.object(tasks.servers, 'get_all', return_value=self.SERVERS).start()
        self.app_update = mock.patch.object(
            tasks.steam, 'app_update', return_value=(True, None, 'ok')).start()
        self.installed = mock.patch.object(
            tasks.steam, 'installed_app_state', return_value=({'buildid': '1'}, None)).start()
        self.addCleanup(mock.patch.stopall)

    def _run(self, states):
        mock.patch.object(tasks.cache, 'get_value',
                          side_effect=lambda key: states.get(key)).start()
        data = {}
        return tasks.update_server(data), data

    def test_refused_while_any_server_could_run_the_game(self):
        for state in ('running', 'sleeping', 'restarting', 'booting', None):
            with self.subTest(state=state):
                ok, data = self._run({'server:1:state': 'stopped', 'server:2:state': state})
                self.assertFalse(ok)
                self.assertIn('beta', data['message'])
        self.app_update.assert_not_called()

    def test_allowed_when_everything_is_down_or_held(self):
        ok, _data = self._run({'server:1:state': 'maintenance', 'server:2:state': 'failed'})
        self.assertTrue(ok)
        self.app_update.assert_called_once()

    def test_a_first_install_is_not_blocked(self):
        self.installed.return_value = (None, None)
        ok, _data = self._run({'server:1:state': 'restarting'})
        self.assertTrue(ok)


if __name__ == '__main__':
    unittest.main()

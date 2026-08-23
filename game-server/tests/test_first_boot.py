"""Tests for first-boot provisioning in the server manager.

Same import dance as `test_idle_sleep.py` / `test_crash_loop.py`: `manager_game`
pulls in the service runtime, so these skip unless it is installed, and `pwd` is
stood in on non-Linux hosts.

Project Zomboid writes a server's INI only on its first successful launch, and
much of the panel needs that file. So a server whose config is missing is booted
once to generate it, then dropped to its configured default - unless it was asked
to run anyway, in which case running writes the config on its own.
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


def _make_manager(default_state, config_exists):
    """Build a manager with `_config_exists` forced, logging silenced.

    `_config_exists` is consulted inside __init__ to pick the boot-strap goal, so
    it is patched for the construction itself, not just afterwards.
    """
    with mock.patch.object(manager_game.GameManager, 'log',
                           lambda self, message: None), \
         mock.patch.object(manager_game.GameManager, '_config_exists',
                           return_value=config_exists):
        return manager_game.GameManager(
            1, 'test-server', [16261], initial_state=default_state
        )


@unittest.skipIf(manager_game is None,
                 f"game-server runtime deps not installed ({IMPORT_ERROR})")
class TestFirstBootGoal(unittest.TestCase):
    """What desired state a fresh manager picks."""

    def test_missing_config_with_default_stopped_provisions_first(self):
        manager = _make_manager('stopped', config_exists=False)
        self.assertEqual(manager.state, 'initializing')
        self.assertEqual(manager.default_state, 'stopped')

    def test_missing_config_with_default_sleeping_provisions_first(self):
        manager = _make_manager('sleeping', config_exists=False)
        self.assertEqual(manager.state, 'initializing')
        self.assertEqual(manager.default_state, 'sleeping')

    def test_missing_config_with_default_running_just_runs(self):
        # Running writes the config on its own; no provisioning detour needed.
        manager = _make_manager('running', config_exists=False)
        self.assertEqual(manager.state, 'running')

    def test_existing_config_keeps_the_default(self):
        manager = _make_manager('stopped', config_exists=True)
        self.assertEqual(manager.state, 'stopped')

    def test_existing_config_with_default_sleeping_keeps_it(self):
        manager = _make_manager('sleeping', config_exists=True)
        self.assertEqual(manager.state, 'sleeping')


@unittest.skipIf(manager_game is None,
                 f"game-server runtime deps not installed ({IMPORT_ERROR})")
class TestProvisioningReconcile(unittest.TestCase):
    """A single reconcile pass while the goal is `initializing`."""

    def setUp(self):
        patcher = mock.patch.object(manager_game.GameManager, 'log',
                                    lambda self, message: None)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.manager = _make_manager('stopped', config_exists=False)
        # Don't actually spawn a JVM; just record that a boot was asked for.
        proc_patcher = mock.patch.object(self.manager, 'manage_server_process')
        self.manage_process = proc_patcher.start()
        self.addCleanup(proc_patcher.stop)

    def test_it_boots_once_when_the_config_is_missing(self):
        with mock.patch.object(self.manager, '_config_exists', return_value=False):
            self.manager._reconcile_initializing(game_alive=False)
        self.manage_process.assert_called_once_with(start=True)
        self.assertEqual(self.manager.state, 'initializing')

    def test_a_boot_that_is_not_yet_up_keeps_waiting(self):
        # The INI can appear early in boot; the roster answer is the real proof.
        self.manager._roster_ready = False
        self.manager._reconcile_initializing(game_alive=True)
        self.assertEqual(self.manager.state, 'initializing')
        self.manage_process.assert_not_called()

    def test_a_finished_boot_drops_to_the_default(self):
        self.manager._roster_ready = True
        self.manager._reconcile_initializing(game_alive=True)
        self.assertEqual(self.manager.state, 'stopped')

    def test_a_config_appearing_before_boot_skips_straight_to_the_default(self):
        # A manager restart that found the INI already there never needs to boot.
        with mock.patch.object(self.manager, '_config_exists', return_value=True):
            self.manager._reconcile_initializing(game_alive=False)
        self.manage_process.assert_not_called()
        self.assertEqual(self.manager.state, 'stopped')

    def test_it_does_not_boot_once_it_has_given_up(self):
        # A crash-looping first boot parks, exactly like a "running" one.
        with mock.patch.object(self.manager, '_config_exists', return_value=False), \
             mock.patch.object(self.manager, '_may_restart', return_value=False):
            self.manager._reconcile_initializing(game_alive=False)
        self.manage_process.assert_not_called()
        self.assertEqual(self.manager.state, 'initializing')

    def test_a_running_default_comes_up_after_provisioning(self):
        manager = _make_manager('running', config_exists=False)
        # It was asked to run, so it never entered the initializing goal at all.
        self.assertEqual(manager.state, 'running')


if __name__ == '__main__':
    unittest.main()

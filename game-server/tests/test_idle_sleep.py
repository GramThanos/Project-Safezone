"""Tests for the idle auto-sleep timeout in the server manager.

Same import dance as `test_crash_loop.py`: `manager_game` pulls in the service
runtime, so these skip unless it is installed, and `pwd` is stood in on non-Linux
hosts.

The timeout exists because a server nobody is on still costs a full JVM heap.
The subtlety it has to get right is that an empty roster is not always idleness -
it is also what a server looks like for the several minutes it spends loading its
world, and sleeping then would put it away just as it became joinable.
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


class FakeClock:
    """A monotonic clock the test drives by hand."""

    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@unittest.skipIf(manager_game is None,
                 f"game-server runtime deps not installed ({IMPORT_ERROR})")
class TestIdleSleep(unittest.TestCase):

    IDLE = 300

    def setUp(self):
        patcher = mock.patch.object(manager_game.GameManager, 'log',
                                    lambda self, message: None)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.clock = FakeClock()
        clock_patcher = mock.patch.object(manager_game.time, 'monotonic', self.clock)
        clock_patcher.start()
        self.addCleanup(clock_patcher.stop)

        self.manager = manager_game.GameManager(
            1, 'test-server', [16261], initial_state='running',
            idle_sleep_seconds=self.IDLE
        )
        # The server has answered a `players` query, so it is genuinely up.
        self.manager._roster_ready = True

    def _idle_for(self, seconds):
        """Let the timeout accrue, checking in the way the reconcile loop does."""
        self.manager._check_idle_sleep()
        self.clock.advance(seconds)
        self.manager._check_idle_sleep()

    def test_an_empty_server_sleeps_once_the_timeout_elapses(self):
        self._idle_for(self.IDLE)
        self.assertEqual(self.manager.state, 'sleeping')

    def test_it_stays_up_until_the_timeout_elapses(self):
        self._idle_for(self.IDLE - 1)
        self.assertEqual(self.manager.state, 'running')

    def test_a_player_joining_resets_the_clock(self):
        self._idle_for(self.IDLE - 1)
        self.manager.online_players = ['Alice']
        self.manager._check_idle_sleep()
        self.assertIsNone(self.manager._idle_since)

        # They leave; the full timeout has to pass again from here.
        self.manager.online_players = []
        self._idle_for(self.IDLE - 1)
        self.assertEqual(self.manager.state, 'running')
        self.clock.advance(1)
        self.manager._check_idle_sleep()
        self.assertEqual(self.manager.state, 'sleeping')

    def test_a_populated_server_never_sleeps(self):
        self.manager.online_players = ['Alice']
        self._idle_for(self.IDLE * 10)
        self.assertEqual(self.manager.state, 'running')

    def test_zero_disables_the_timeout(self):
        self.manager.idle_sleep_seconds = 0
        self._idle_for(self.IDLE * 10)
        self.assertEqual(self.manager.state, 'running')
        self.assertIsNone(self.manager._idle_since)

    def test_a_loading_world_is_not_idle(self):
        """The clock must not start before the server has answered `players`."""
        self.manager._roster_ready = False
        self._idle_for(self.IDLE * 10)
        self.assertEqual(self.manager.state, 'running')
        self.assertIsNone(self.manager._idle_since)

        # Once it answers, the timeout starts from that moment - not from boot.
        self.manager._roster_ready = True
        self._idle_for(self.IDLE - 1)
        self.assertEqual(self.manager.state, 'running')

    def test_changing_the_desired_state_clears_the_clock(self):
        self.manager._check_idle_sleep()
        self.assertIsNotNone(self.manager._idle_since)
        self.manager.state = 'stopped'
        self.assertIsNone(self.manager._idle_since)

    def test_raising_the_timeout_restarts_the_countdown(self):
        self._idle_for(self.IDLE - 1)
        self.manager.set_idle_sleep_seconds(self.IDLE * 2)
        self.assertIsNone(self.manager._idle_since)

        # The old timeout would have fired here; the new one has not.
        self.clock.advance(1)
        self.manager._check_idle_sleep()
        self.assertEqual(self.manager.state, 'running')

    def test_setting_the_same_timeout_leaves_the_countdown_alone(self):
        self.manager._check_idle_sleep()
        armed_at = self.manager._idle_since
        self.manager.set_idle_sleep_seconds(self.IDLE)
        self.assertEqual(self.manager._idle_since, armed_at)

    def test_disabling_it_on_a_live_manager_stops_the_countdown(self):
        self._idle_for(self.IDLE - 1)
        self.manager.set_idle_sleep_seconds(0)
        self._idle_for(self.IDLE * 10)
        self.assertEqual(self.manager.state, 'running')


@unittest.skipIf(manager_game is None,
                 f"game-server runtime deps not installed ({IMPORT_ERROR})")
class TestIdleSleepDefaults(unittest.TestCase):

    def test_it_is_off_unless_configured(self):
        with mock.patch.object(manager_game.GameManager, 'log',
                               lambda self, message: None):
            manager = manager_game.GameManager(1, 'test-server', [16261])
        self.assertEqual(manager.idle_sleep_seconds, 0)

    def test_none_is_treated_as_disabled(self):
        with mock.patch.object(manager_game.GameManager, 'log',
                               lambda self, message: None):
            manager = manager_game.GameManager(1, 'test-server', [16261],
                                               idle_sleep_seconds=None)
        self.assertEqual(manager.idle_sleep_seconds, 0)


if __name__ == '__main__':
    unittest.main()

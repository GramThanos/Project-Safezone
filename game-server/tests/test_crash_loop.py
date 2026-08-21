"""Tests for the crash-loop guard in the server orchestrator.

`manager_game` pulls in the service runtime (redis, sqlalchemy), so these skip
unless those are installed - but unlike the other suites they do run off Linux,
see the `pwd` note below.

The guard exists because restarting a dead server is the right reflex but an
unbounded one hides the outage: a server that dies on startup would otherwise
respawn every health check forever while the UI flickers back to "running".
"""
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# `steam.py` imports the Unix-only `pwd` module at import time, which makes the
# whole manager import chain unloadable off Linux. Nothing the crash-loop guard
# touches uses it, so stand in a placeholder when it is genuinely missing rather
# than leaving these tests runnable only inside the container.
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
class TestCrashLoopGuard(unittest.TestCase):

    def setUp(self):
        # Silence the manager's own logging for the duration of each test.
        patcher = mock.patch.object(manager_game.GameManager, 'log',
                                    lambda self, message: None)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.clock = FakeClock()
        clock_patcher = mock.patch.object(manager_game.time, 'monotonic', self.clock)
        clock_patcher.start()
        self.addCleanup(clock_patcher.stop)

        self.manager = manager_game.GameManager(
            1, 'test-server', [16261], initial_state='running'
        )

    def _restart_once(self):
        """Take one allowed restart, then wait out the backoff it imposed."""
        allowed = self.manager._may_restart()
        self.clock.advance(self.manager._backoff_until - self.clock.now)
        return allowed

    def test_first_restart_is_allowed_immediately(self):
        self.assertTrue(self.manager._may_restart())

    def test_backoff_blocks_the_next_restart_until_it_elapses(self):
        self.assertTrue(self.manager._may_restart())
        # Still inside the backoff window.
        self.assertFalse(self.manager._may_restart())
        self.clock.advance(self.manager.crash_backoff_base)
        self.assertTrue(self.manager._may_restart())

    def test_backoff_grows_with_each_consecutive_restart(self):
        delays = []
        for _ in range(3):
            self.manager._may_restart()
            delays.append(self.manager._backoff_until - self.clock.now)
            self.clock.advance(delays[-1])
        self.assertEqual(delays, [5, 10, 20])

    def test_gives_up_after_the_threshold(self):
        for i in range(self.manager.crash_threshold):
            self.assertTrue(self._restart_once(), f"restart {i} should be allowed")

        # One more crash inside the window is the loop verdict.
        self.assertFalse(self.manager._may_restart())
        self.assertTrue(self.manager._failed)

    def test_a_failed_manager_stops_retrying(self):
        for _ in range(self.manager.crash_threshold):
            self._restart_once()
        self.manager._may_restart()          # trips the verdict
        self.clock.advance(10_000)           # long past any backoff
        self.assertFalse(self.manager._may_restart())

    def test_failure_is_published_as_its_own_state(self):
        self.manager._failed = True
        with mock.patch.object(manager_game.cache, 'set_value') as set_value:
            self.manager._publish_live_state()
        # Not "stopped" - nobody asked for this one.
        self.assertEqual(set_value.call_args[0][1], 'failed')

    def test_changing_the_desired_state_clears_the_verdict(self):
        for _ in range(self.manager.crash_threshold):
            self._restart_once()
        self.manager._may_restart()
        self.assertTrue(self.manager._failed)

        # An operator asking for a different state means "try again".
        self.manager.state = 'stopped'

        self.assertFalse(self.manager._failed)
        self.assertEqual(self.manager._restart_times, [])
        self.assertTrue(self.manager._may_restart())

    def test_setting_the_same_state_does_not_clear_the_verdict(self):
        self.manager._failed = True
        self.manager.state = 'running'  # already running; no actual change
        self.assertTrue(self.manager._failed)

    def test_a_sustained_run_forgets_earlier_crashes(self):
        self._restart_once()
        self.manager._last_start_at = self.clock.now
        self.assertNotEqual(self.manager._restart_times, [])

        # Stayed up longer than the window that defines a "recent" restart.
        self.clock.advance(self.manager.crash_window + 1)
        self.manager._note_healthy_run()

        self.assertEqual(self.manager._restart_times, [])

    def test_a_short_run_still_counts_toward_the_loop(self):
        self._restart_once()
        self.manager._last_start_at = self.clock.now
        self.clock.advance(5)
        self.manager._note_healthy_run()
        self.assertNotEqual(self.manager._restart_times, [])


if __name__ == '__main__':
    unittest.main()

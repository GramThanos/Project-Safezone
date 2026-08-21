"""Tests for what is allowed to wake a sleeping server.

Same import dance as `test_crash_loop.py`.

Any datagram used to trigger a wake, which meant a port scan - or, on a
Steam-enabled server, a browser refreshing its list - booted the whole game
server for nobody. 16261/16262 are a known Project Zomboid signature and are
swept constantly, so in practice a sleeping server woke itself within minutes.

The filtering is deliberately protocol-agnostic: PZ's handshake format is not
known here, so the tests pin the two properties that do not depend on it.
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
class TestQueryPacketFilter(unittest.TestCase):
    """Server-browser traffic is somebody looking, not somebody joining."""

    def test_a2s_info_is_a_query(self):
        packet = b'\xff\xff\xff\xffTSource Engine Query\x00'
        self.assertTrue(manager_game.GameManager._is_query_packet(packet))

    def test_every_connectionless_header_is_a_query(self):
        # A2S_PLAYER, A2S_RULES, and the challenge reply share the prefix.
        for header in (b'U', b'V', b'A'):
            with self.subTest(header=header):
                self.assertTrue(
                    manager_game.GameManager._is_query_packet(
                        b'\xff\xff\xff\xff' + header)
                )

    def test_game_traffic_is_not_a_query(self):
        self.assertFalse(manager_game.GameManager._is_query_packet(b'\x01\x02handshake'))

    def test_a_partial_prefix_is_not_a_query(self):
        self.assertFalse(manager_game.GameManager._is_query_packet(b'\xff\xff\x00\x00junk'))


@unittest.skipIf(manager_game is None,
                 f"game-server runtime deps not installed ({IMPORT_ERROR})")
class TestWakeThreshold(unittest.TestCase):
    """A real client retries; a sweep sends one packet and moves on."""

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
            1, 'test-server', [16261], initial_state='sleeping'
        )

    def test_one_packet_is_not_enough(self):
        self.assertFalse(self.manager._note_wake_packet('203.0.113.1'))

    def test_the_threshold_wakes(self):
        self.manager.wake_packet_threshold = 3
        results = [self.manager._note_wake_packet('203.0.113.1') for _ in range(3)]
        self.assertEqual(results, [False, False, True])

    def test_the_default_threshold_favours_waking(self):
        """A missed wake is worse than a spare boot, so the bar is deliberately low."""
        self.assertFalse(self.manager._note_wake_packet('203.0.113.1'))
        self.assertTrue(self.manager._note_wake_packet('203.0.113.1'))

    def test_a_sweep_across_many_addresses_never_wakes(self):
        """One probe per host is what a sweep looks like, however many hosts."""
        for i in range(500):
            woke = self.manager._note_wake_packet(f'203.0.{i // 254}.{i % 254}')
            self.assertFalse(woke)

    def test_a_scanner_that_probes_twice_does_get_through(self):
        """The accepted cost of biasing towards waking.

        Pinned so the trade-off is visible rather than discovered: a repeat
        prober still wakes the server. Idle-sleep is what bounds it - the server
        boots, nobody joins, and it puts itself away again.
        """
        self.assertFalse(self.manager._note_wake_packet('203.0.113.1'))
        self.clock.advance(5)
        self.assertTrue(self.manager._note_wake_packet('203.0.113.1'))

    def test_packets_that_age_out_do_not_count(self):
        self.manager.wake_packet_threshold = 3
        self.manager._note_wake_packet('203.0.113.1')
        self.manager._note_wake_packet('203.0.113.1')
        # A scanner that comes back much later starts from scratch.
        self.clock.advance(self.manager.wake_packet_window + 1)
        self.assertFalse(self.manager._note_wake_packet('203.0.113.1'))

    def test_a_client_retrying_within_the_window_wakes(self):
        self.manager.wake_packet_threshold = 3
        self.assertFalse(self.manager._note_wake_packet('203.0.113.1'))
        self.clock.advance(2)
        self.assertFalse(self.manager._note_wake_packet('203.0.113.1'))
        self.clock.advance(2)
        self.assertTrue(self.manager._note_wake_packet('203.0.113.1'))

    def test_a_slow_retry_still_wakes(self):
        """The window has to outlast whatever PZ's retry interval turns out to be."""
        self.assertFalse(self.manager._note_wake_packet('203.0.113.1'))
        self.clock.advance(30)
        self.assertTrue(self.manager._note_wake_packet('203.0.113.1'))

    def test_the_source_map_stays_bounded(self):
        self.manager.wake_sources_max = 16
        for i in range(200):
            self.manager._note_wake_packet(f'10.0.{i // 254}.{i % 254}')
        self.clock.advance(self.manager.wake_packet_window + 1)
        # One more packet triggers the prune, which drops everything aged out.
        self.manager._note_wake_packet('10.1.1.1')
        self.assertLessEqual(len(self.manager._wake_packets), 17)

    def test_the_map_is_cleared_when_the_listener_restarts(self):
        self.manager.wake_packet_threshold = 3
        self.manager._note_wake_packet('203.0.113.1')
        self.manager._note_wake_packet('203.0.113.1')
        # Binding nothing returns early, but the map is reset on the way in, so
        # a stale near-threshold count cannot carry into the next listener.
        with mock.patch.object(manager_game.socket, 'socket',
                               side_effect=OSError('port in use')):
            self.manager._onwake_worker()
        self.assertEqual(self.manager._wake_packets, {})


@unittest.skipIf(manager_game is None,
                 f"game-server runtime deps not installed ({IMPORT_ERROR})")
class TestBindFailure(unittest.TestCase):
    """Binding nothing means the server cannot be woken - say so, once."""

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
            1, 'test-server', [16261], initial_state='sleeping'
        )

    def _fail_to_bind(self):
        with mock.patch.object(manager_game.socket, 'socket',
                               side_effect=OSError('port in use')):
            self.manager._onwake_worker()

    def test_a_total_bind_failure_is_recorded(self):
        self._fail_to_bind()
        self.assertTrue(self.manager._wake_bind_failed)

    def test_it_backs_off_instead_of_respawning_every_pass(self):
        self._fail_to_bind()
        # The reconcile loop's gate: not yet.
        self.assertGreater(self.manager._wake_retry_after, self.clock.now)
        self.clock.advance(self.manager.wake_bind_retry_interval)
        self.assertLessEqual(self.manager._wake_retry_after, self.clock.now)

    def test_an_unwakeable_server_is_not_reported_as_stopped(self):
        self._fail_to_bind()
        with mock.patch.object(manager_game.cache, 'set_value') as set_value:
            self.manager._publish_live_state()
        # "stopped" would mean somebody asked for this.
        self.assertEqual(set_value.call_args[0][1], 'failed')

    def test_asking_for_a_state_again_clears_the_verdict(self):
        self._fail_to_bind()
        self.manager.state = 'stopped'
        self.assertFalse(self.manager._wake_bind_failed)
        self.assertEqual(self.manager._wake_retry_after, 0.0)


if __name__ == '__main__':
    unittest.main()

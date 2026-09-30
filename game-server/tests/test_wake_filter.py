"""Tests for what is allowed to wake a sleeping server.

Same import dance as `test_crash_loop.py`.

A sleeping server keeps a UDP listener on the game ports so it stays visible in
the server browser. The danger is waking the whole JVM for nobody: 16261/16262
are a known Project Zomboid signature and are swept constantly, and a Steam
browser refreshing its list pings every server it knows. Neither is somebody
joining.

A Steam client's actual join is brokered by Steam's networking layer, not sent
as a UDP packet to the game port, so the join itself never reaches the listener.
The only signal a sleeping server gets that somebody wants in is the client's
A2S query. So there are two wake paths:

  * The direct-IP / non-Steam path, where the join really is a UDP packet: an
    explicit RakNet connection request wakes immediately.
  * The Steam path, where there is no join packet: a source that completes the
    IP-bound challenge and issues enough authenticated A2S_INFO queries inside
    the window is treated as a join attempt. PLAYER/RULES queries and the
    challenge round-trip are answered to stay visible but do not by themselves
    wake, and a stray scan datagram is ignored entirely.

These tests pin the classifiers, the direct-IP join, and the A2S-intent
threshold. The threshold is what stops a single stray probe from waking the
whole JVM for nobody while still letting a real client in.
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


def _make_manager():
    """A sleeping manager with logging silenced, for the classifier methods.

    The wake classifiers read instance constants (the A2S header, the RakNet
    packet ids), so they need a real instance rather than being called on the
    class.
    """
    with mock.patch.object(manager_game.GameManager, 'log',
                           lambda self, message: None):
        return manager_game.GameManager(
            1, 'test-server', [16261], initial_state='sleeping'
        )


# Well-formed sample datagrams for each protocol shape the listener sees.
def _a2s_info():
    return b'\xff\xff\xff\xffTSource Engine Query\x00'


def _raknet_ping(packet_id=None):
    ping_id = (packet_id if packet_id is not None
               else manager_game.GameManager.RAKNET_ID_UNCONNECTED_PING)
    # id + 8-byte client timestamp + 16-byte magic == 25 bytes, the minimum the
    # classifier accepts.
    return (bytes([ping_id]) + b'\x00' * 8
            + manager_game.GameManager.RAKNET_MAGIC)


def _connection_request():
    # OPEN_CONNECTION_REQUEST_1: id + magic + one protocol byte, comfortably
    # past the 18-byte floor.
    return (bytes([manager_game.GameManager.RAKNET_ID_OPEN_CONNECTION_REQUEST_1])
            + manager_game.GameManager.RAKNET_MAGIC + b'\x00')


@unittest.skipIf(manager_game is None,
                 f"game-server runtime deps not installed ({IMPORT_ERROR})")
class TestServerInfoRequestFilter(unittest.TestCase):
    """Server-browser traffic is somebody looking, not somebody joining."""

    def setUp(self):
        self.manager = _make_manager()

    def test_a2s_info_is_a_server_info_request(self):
        self.assertTrue(self.manager._is_server_info_request(_a2s_info()))

    def test_raknet_unconnected_ping_is_a_server_info_request(self):
        self.assertTrue(self.manager._is_server_info_request(_raknet_ping()))

    def test_raknet_open_ping_is_a_server_info_request(self):
        self.assertTrue(self.manager._is_server_info_request(
            _raknet_ping(manager_game.GameManager.RAKNET_ID_UNCONNECTED_PING_OPEN)))

    def test_a_connection_request_is_not_a_server_info_request(self):
        # A join is not a browse: the two classifiers must not both claim it, or
        # a real client would be answered with fake info instead of woken.
        self.assertFalse(self.manager._is_server_info_request(_connection_request()))

    def test_a_short_scan_datagram_is_not_a_server_info_request(self):
        # A RakNet id byte without the length that follows a real ping.
        self.assertFalse(self.manager._is_server_info_request(b'\x01\x02\x03'))

    def test_a_partial_a2s_prefix_is_not_a_server_info_request(self):
        self.assertFalse(self.manager._is_server_info_request(b'\xff\xff\x00\x00junk'))


@unittest.skipIf(manager_game is None,
                 f"game-server runtime deps not installed ({IMPORT_ERROR})")
class TestConnectionAttemptWakes(unittest.TestCase):
    """Only the first packet of an actual join is allowed to wake the server."""

    def setUp(self):
        self.manager = _make_manager()

    def test_a_connection_request_is_a_join(self):
        self.assertTrue(self.manager._player_trying_to_connect(_connection_request()))

    def test_a_browser_ping_is_not_a_join(self):
        # The whole point: a sweep or a browser refresh must not wake anything.
        self.assertFalse(self.manager._player_trying_to_connect(_a2s_info()))
        self.assertFalse(self.manager._player_trying_to_connect(_raknet_ping()))

    def test_a_short_datagram_is_not_a_join(self):
        # OPEN_CONNECTION_REQUEST_1 id byte, but nothing behind it.
        self.assertFalse(self.manager._player_trying_to_connect(
            bytes([manager_game.GameManager.RAKNET_ID_OPEN_CONNECTION_REQUEST_1])))

    def test_a_sweep_across_many_shapes_never_wakes(self):
        """However many probes a scan sends, none of them is a join."""
        for i in range(256):
            datagram = bytes([i]) + b'\x00' * 24
            if datagram[0] == manager_game.GameManager.RAKNET_ID_OPEN_CONNECTION_REQUEST_1:
                continue  # that byte IS the join id; every other one is a scan
            self.assertFalse(self.manager._player_trying_to_connect(datagram))


@unittest.skipIf(manager_game is None,
                 f"game-server runtime deps not installed ({IMPORT_ERROR})")
class TestA2sIntentWakes(unittest.TestCase):
    """The Steam path: repeated authenticated A2S_INFO is the only join signal."""

    def setUp(self):
        self.clock = FakeClock()
        patcher = mock.patch.object(manager_game.time, 'monotonic', self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.manager = _make_manager()
        self.manager.wake_a2s_threshold = 2
        self.manager.wake_a2s_window = 60.0

    def test_it_wakes_only_once_the_threshold_is_reached(self):
        # One authenticated query is a browse; the second inside the window is a
        # client that keeps asking - that is the one allowed to wake.
        self.assertFalse(self.manager._note_a2s_intent('1.2.3.4'))
        self.assertTrue(self.manager._note_a2s_intent('1.2.3.4'))

    def test_hits_outside_the_window_do_not_count(self):
        self.assertFalse(self.manager._note_a2s_intent('1.2.3.4'))
        self.clock.advance(self.manager.wake_a2s_window + 1)
        # The earlier hit has aged out, so this is a first hit again, not a wake.
        self.assertFalse(self.manager._note_a2s_intent('1.2.3.4'))

    def test_one_query_each_from_many_sources_never_wakes(self):
        # A sweep touching the port once from a thousand addresses is not a join.
        for i in range(1000):
            self.assertFalse(self.manager._note_a2s_intent(f'10.0.{i // 256}.{i % 256}'))

    def test_a_threshold_of_one_wakes_on_first_contact(self):
        # The eager setting a busy server might choose so no join is ever missed.
        self.manager.wake_a2s_threshold = 1
        self.assertTrue(self.manager._note_a2s_intent('1.2.3.4'))


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

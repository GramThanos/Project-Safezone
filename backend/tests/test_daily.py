"""Tests for the daily reset boundary (primary server's timezone).

`src.utils.daily` reaches the game-server through `src.utils.game_server`, which
needs flask/requests, so these run in the backend container and skip on a bare
host.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    from src.utils import daily
    IMPORT_ERROR = None
except ImportError as exc:  # pragma: no cover - depends on the environment
    daily = None
    IMPORT_ERROR = exc


def _servers(*entries):
    return {'data': list(entries)}, 200


@unittest.skipIf(daily is None, f"backend runtime deps not installed ({IMPORT_ERROR})")
class TestPrimaryTimezone(unittest.TestCase):
    def setUp(self):
        daily.reset_cache()

    def tearDown(self):
        daily.reset_cache()

    def test_lowest_id_with_a_timezone_wins(self):
        response = _servers(
            {'id': 3, 'timezone': 'Asia/Tokyo'},
            {'id': 1, 'timezone': 'Europe/Athens'},
            {'id': 2, 'timezone': 'America/New_York'},
        )
        with mock.patch.object(daily, 'gs_request', return_value=response):
            self.assertEqual(str(daily.primary_timezone()), 'Europe/Athens')

    def test_servers_without_a_timezone_are_skipped(self):
        response = _servers(
            {'id': 1, 'timezone': None},
            {'id': 2, 'timezone': '   '},
            {'id': 3, 'timezone': 'Europe/Athens'},
        )
        with mock.patch.object(daily, 'gs_request', return_value=response):
            self.assertEqual(str(daily.primary_timezone()), 'Europe/Athens')

    def test_no_timezone_configured_falls_back_to_utc(self):
        response = _servers({'id': 1, 'timezone': None})
        with mock.patch.object(daily, 'gs_request', return_value=response):
            self.assertEqual(str(daily.primary_timezone()), 'UTC')

    def test_unusable_timezone_falls_back_to_utc(self):
        response = _servers({'id': 1, 'timezone': 'Mars/Olympus_Mons'})
        with mock.patch.object(daily, 'gs_request', return_value=response):
            self.assertEqual(str(daily.primary_timezone()), 'UTC')

    def test_unreachable_game_server_falls_back_to_utc(self):
        with mock.patch.object(daily, 'gs_request',
                               return_value=({'error': 'Game server unavailable'}, 503)):
            self.assertEqual(str(daily.primary_timezone()), 'UTC')

    def test_result_is_cached(self):
        response = _servers({'id': 1, 'timezone': 'Europe/Athens'})
        with mock.patch.object(daily, 'gs_request', return_value=response) as gs:
            daily.primary_timezone()
            daily.primary_timezone()
        self.assertEqual(gs.call_count, 1)

    def test_today_uses_the_resolved_zone(self):
        """A zone far from UTC must be able to report a different calendar day."""
        import datetime
        response = _servers({'id': 1, 'timezone': 'Pacific/Kiritimati'})  # UTC+14
        with mock.patch.object(daily, 'gs_request', return_value=response):
            local_today = daily.today()
        utc_today = datetime.datetime.now(daily.UTC).date()
        self.assertIn((local_today - utc_today).days, (0, 1))


if __name__ == '__main__':
    unittest.main()

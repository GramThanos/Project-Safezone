"""Tests for the bucketing behind the public player-activity chart.

`servers` pulls in the database layer, so like the manager suites these skip
when the service runtime is not installed.

The chart is read by people in any timezone, so every point has to carry an
explicit offset, and it has to span the whole window: a server that slept all
night records nothing, and a series that simply stopped at the last sample
made the chart look like it ended hours ago.
"""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

try:
    import servers
    IMPORT_ERROR = None
except Exception as e:  # pragma: no cover - depends on the host
    servers = None
    IMPORT_ERROR = e


@unittest.skipIf(servers is None, f"service runtime unavailable: {IMPORT_ERROR}")
class BucketPlayerCountsTest(unittest.TestCase):
    NOW = datetime.datetime(2026, 10, 11, 10, 7)
    SINCE = NOW - datetime.timedelta(hours=1)

    def bucket(self, rows):
        return servers.bucket_player_counts(rows, self.SINCE, self.NOW, 15)

    def test_spans_the_whole_window_with_zeros(self):
        history = self.bucket([])
        self.assertEqual(len(history), 5)  # 09:00, 09:15, 09:30, 09:45, 10:00
        self.assertTrue(all(p['count'] == 0 for p in history))
        last = datetime.datetime.fromisoformat(history[-1]['t'])
        self.assertLessEqual(last.timestamp(), self.NOW.timestamp())
        self.assertGreater(last.timestamp() + 15 * 60, self.NOW.timestamp())

    def test_times_carry_a_utc_offset(self):
        for point in self.bucket([]):
            self.assertTrue(point['t'].endswith('+00:00'), point['t'])

    def test_a_bucket_shows_its_peak(self):
        at = datetime.datetime(2026, 10, 11, 9, 31)
        history = self.bucket([(0, at), (3, at + datetime.timedelta(minutes=2)), (1, at)])
        counts = {datetime.datetime.fromisoformat(p['t']).timestamp(): p['count'] for p in history}
        start = int(at.timestamp()) - int(at.timestamp()) % 900
        self.assertEqual(counts[start], 3)
        self.assertEqual(sum(counts.values()), 3)

    def test_samples_without_a_time_are_ignored(self):
        self.assertTrue(all(p['count'] == 0 for p in self.bucket([(5, None)])))


if __name__ == '__main__':
    unittest.main()

"""Tests for the alert dispatch pool.

`emit()` used to start a thread per event with no ceiling. What replaced it has
to keep the one promise the old code did keep - the caller is never blocked or
raised at - while adding the one it did not: a bound on what an alert storm
costs.
"""
import os
import queue
import sys
import threading
import unittest

from flask import Flask

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.utils import alerting  # noqa: E402


class PoolTestCase(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.addCleanup(self._drain)

    def _drain(self):
        while True:
            try:
                alerting._dispatch_queue.get_nowait()
                alerting._dispatch_queue.task_done()
            except queue.Empty:
                return

    def emit(self, event):
        with self.app.app_context():
            alerting.emit(event, f'title for {event}')

    def queued_events(self):
        # item is (app, args, kwargs); args is (event, title)
        return [item[1][0] for item in list(alerting._dispatch_queue.queue)]


class TestQueueBound(PoolTestCase):
    """Deterministic: the workers are marked started but never actually run, so
    nothing drains underneath the assertions.

    The flag is restored afterwards. `TestPoolDrains` deliberately does not
    restore it, because there the workers are real and resetting the flag would
    start a second pool on the next call.
    """

    def setUp(self):
        super().setUp()
        started = alerting._workers_started
        alerting._workers_started = True
        self.addCleanup(lambda: setattr(alerting, '_workers_started', started))

    def test_queue_does_not_grow_past_its_bound(self):
        for n in range(alerting._QUEUE_MAX + 50):
            self.emit(f'e{n}')
        self.assertEqual(alerting._dispatch_queue.qsize(), alerting._QUEUE_MAX)

    def test_a_full_queue_sheds_the_oldest_not_the_newest(self):
        for n in range(alerting._QUEUE_MAX):
            self.emit(f'e{n}')
        self.emit('newest')

        events = self.queued_events()
        self.assertIn('newest', events, 'the newest event must survive')
        self.assertNotIn('e0', events, 'the oldest event should have been shed')
        self.assertEqual(len(events), alerting._QUEUE_MAX)

    def test_emit_never_raises_when_saturated(self):
        # The whole point of the module: announcing must not break the thing
        # being announced.
        for n in range(alerting._QUEUE_MAX * 2):
            self.emit(f'e{n}')   # would raise queue.Full if put_nowait escaped


class TestPoolDrains(PoolTestCase):
    def test_emitted_events_reach_dispatch(self):
        seen = []
        done = threading.Event()
        original = alerting.dispatch

        def fake_dispatch(event, title, **kwargs):
            seen.append(event)
            if len(seen) == 3:
                done.set()

        alerting.dispatch = fake_dispatch
        self.addCleanup(lambda: setattr(alerting, 'dispatch', original))

        for n in range(3):
            self.emit(f'event-{n}')

        self.assertTrue(done.wait(timeout=10), f'pool did not drain; saw {seen}')
        self.assertCountEqual(seen, ['event-0', 'event-1', 'event-2'])

    def test_a_failing_dispatch_does_not_kill_the_worker(self):
        """A worker that dies takes half the pool with it, permanently."""
        seen = []
        done = threading.Event()
        original = alerting.dispatch

        def fake_dispatch(event, title, **kwargs):
            if event == 'boom':
                raise RuntimeError('dispatch exploded')
            seen.append(event)
            done.set()

        alerting.dispatch = fake_dispatch
        self.addCleanup(lambda: setattr(alerting, 'dispatch', original))

        self.emit('boom')
        self.emit('after')

        self.assertTrue(done.wait(timeout=10),
                        'the pool stopped working after one bad event')
        self.assertEqual(seen, ['after'])

    def test_the_pool_is_fixed_size(self):
        alerting._ensure_workers()
        before = len([t for t in threading.enumerate()
                      if t.name.startswith('alert-worker-')])
        for n in range(50):
            self.emit(f'e{n}')
        after = len([t for t in threading.enumerate()
                     if t.name.startswith('alert-worker-')])

        self.assertEqual(before, after, 'emitting must not start new threads')
        self.assertLessEqual(after, alerting._WORKER_COUNT)


if __name__ == '__main__':
    unittest.main()

"""Tests for how the maintenance worker moves a run along.

The store is replaced by mocks, so these pin down the worker's side of the
contract: what it does with a run in each state, given who is online and what
the servers report. The rules it consults are tested in `test_maintenance.py`.

Same import dance as `test_crash_loop.py`.
"""
import datetime
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
    import maintenance
    import manager_maintenance
    IMPORT_ERROR = None
except Exception as e:  # pragma: no cover - depends on the host
    manager_maintenance = None
    IMPORT_ERROR = e

NOW = datetime.datetime(2026, 10, 5, 12, 0, 0)


def server(state, players=0, name='alpha'):
    return {'id': 1, 'name': name, 'state': state, 'players': players}


@unittest.skipIf(manager_maintenance is None,
                 f"game-server runtime deps not installed ({IMPORT_ERROR})")
class TestAdvance(unittest.TestCase):

    def setUp(self):
        mock.patch.object(manager_maintenance, '_log', lambda message: None).start()
        self.store = mock.patch.object(manager_maintenance, 'store').start()
        self.store.transition.side_effect = lambda run_id, expected, status, **kw: dict(
            self.run, status=status, **{k: v for k, v in kw.items() if k not in ('note',)})
        self.addCleanup(mock.patch.stopall)
        self.worker = manager_maintenance.MaintenanceWorker()
        self.worker._start_update = mock.Mock()
        self.policy = maintenance.policy_with_defaults({'countdown': [300, 30]})
        self.run = {'id': 7, 'status': 'scheduled', 'force_at': None, 'deadline': None,
                    'countdown_ends_at': None, 'announced': [], 'started_at': None,
                    'reason': None, 'targets': {'game': None, 'mods': [{'id': '1'}]}}

    def advance(self, states, window=False, now=NOW):
        self.worker._advance(self.run, self.policy, states, window, now)

    def statuses(self):
        return [c.args[2] for c in self.store.transition.call_args_list]

    def test_scheduled_waits_while_people_play(self):
        self.advance([server('running', players=2)])
        self.store.transition.assert_not_called()

    def test_scheduled_goes_straight_down_when_empty_and_holds(self):
        self.advance([server('sleeping')])
        self.assertEqual(self.statuses(), ['stopping'])
        self.store.set_hold.assert_called_once_with(7)
        self.store.broadcast.assert_not_called()

    def test_the_window_starts_a_countdown_with_the_first_warning(self):
        self.advance([server('running', players=2)], window=True)
        self.assertEqual(self.statuses(), ['announcing'])
        self.store.broadcast.assert_called_once()
        self.assertIn('5 minutes', self.store.broadcast.call_args.args[0])
        self.store.set_hold.assert_not_called()

    def test_announcing_stops_early_when_everybody_leaves(self):
        self.run.update(status='announcing',
                        countdown_ends_at=(NOW + datetime.timedelta(seconds=200)).isoformat() + 'Z')
        self.advance([server('running', players=0)])
        self.assertEqual(self.statuses(), ['stopping'])

    def test_announcing_stops_when_the_countdown_ends(self):
        self.run.update(status='announcing', announced=[300, 30],
                        countdown_ends_at=NOW.isoformat() + 'Z')
        self.advance([server('running', players=3)])
        self.assertEqual(self.statuses(), ['stopping'])

    def test_stopping_moves_to_updating_once_every_server_is_down(self):
        started = NOW - datetime.timedelta(seconds=manager_maintenance.MIN_STOPPING_SECONDS)
        self.run.update(status='stopping', started_at=started.isoformat() + 'Z')
        self.advance([server('maintenance'), server('running', name='beta')])
        self.store.transition.assert_not_called()

        self.advance([server('maintenance'), server('maintenance', name='beta')])
        self.assertEqual(self.statuses(), ['updating'])
        self.worker._start_update.assert_called_once()

    def test_a_maintenance_state_from_before_the_hold_is_not_trusted(self):
        # Read straight after the hold was placed, "maintenance" may still be
        # left over from the previous run.
        self.run.update(status='stopping', started_at=NOW.isoformat() + 'Z')
        self.advance([server('maintenance')])
        self.store.transition.assert_not_called()

    def test_stopping_gives_up_and_updates_nothing_after_the_timeout(self):
        started = NOW - datetime.timedelta(seconds=manager_maintenance.config.MAINTENANCE_STOP_TIMEOUT + 1)
        self.run.update(status='stopping', started_at=started.isoformat() + 'Z')
        self.advance([server('running', players=1)])
        self.assertEqual(self.statuses(), ['failed'])
        self.worker._start_update.assert_not_called()

    def test_an_update_with_no_thread_behind_it_was_interrupted(self):
        self.run.update(status='updating')
        self.advance([server('maintenance')])
        self.assertEqual(self.statuses(), ['failed'])

    def test_the_hold_follows_the_run(self):
        self.worker._sync_hold(dict(self.run, status='updating'))
        self.store.set_hold.assert_called_once_with(7)
        self.store.hold_info.return_value = {'run_id': 7}
        self.worker._sync_hold(dict(self.run, status='announcing'))
        self.store.release_hold.assert_called_once()


@unittest.skipIf(manager_maintenance is None,
                 f"game-server runtime deps not installed ({IMPORT_ERROR})")
class TestSchedules(unittest.TestCase):

    def test_a_schedule_fires_once_per_firing_and_not_on_first_sight(self):
        worker = manager_maintenance.MaintenanceWorker()
        utc = datetime.timezone.utc
        at = lambda h, m=0: datetime.datetime(2026, 10, 5, h, m, tzinfo=utc)
        self.assertFalse(worker._cron_due('window', '0 5 * * *', utc, at(4, 59)))
        self.assertFalse(worker._cron_due('window', '0 5 * * *', utc, at(4, 59)))
        self.assertTrue(worker._cron_due('window', '0 5 * * *', utc, at(5, 0)))
        self.assertFalse(worker._cron_due('window', '0 5 * * *', utc, at(5, 0)))

    def test_changing_the_expression_starts_over(self):
        worker = manager_maintenance.MaintenanceWorker()
        utc = datetime.timezone.utc
        moment = datetime.datetime(2026, 10, 5, 5, 0, tzinfo=utc)
        worker._cron_due('window', '0 6 * * *', utc, moment)
        self.assertFalse(worker._cron_due('window', '0 5 * * *', utc, moment))
        self.assertFalse(worker._cron_due('window', '', utc, moment))
        self.assertNotIn('window', worker._schedules)


if __name__ == '__main__':
    unittest.main()

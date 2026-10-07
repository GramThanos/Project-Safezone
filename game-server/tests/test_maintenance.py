"""Tests for the maintenance rules: schedules, the policy, and when a run goes.

What matters here is that a server is never taken down when the policy says it
should not be, and always is when it says it should - so the cron reading, the
decision about a planned run, and the countdown are each pinned down. A
schedule that silently means something other than what was typed is the
failure worth guarding against: nobody notices until the 3am restart happens
at 3pm.
"""
import datetime
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# The same stand-ins as `test_uninstall.py`: `steam` imports `pwd` (Linux only)
# and `vdf`, neither of which the manifest parser under test touches.
try:
    import pwd  # noqa: F401
except ImportError:
    sys.modules['pwd'] = types.ModuleType('pwd')
try:
    import vdf  # noqa: F401
except ImportError:
    sys.modules['vdf'] = types.ModuleType('vdf')

import maintenance  # noqa: E402
import steam  # noqa: E402

D = datetime.datetime


def fires(expression, after, count=3):
    spec = maintenance.parse_cron(expression)
    out, moment = [], after
    for _ in range(count):
        moment = maintenance.next_cron(spec, moment)
        out.append(moment)
    return out


class TestCron(unittest.TestCase):

    def test_every_six_hours(self):
        self.assertEqual(fires('0 */6 * * *', D(2026, 10, 5, 7, 30)),
                         [D(2026, 10, 5, 12), D(2026, 10, 5, 18), D(2026, 10, 6, 0)])

    def test_next_is_strictly_after(self):
        # Asked at exactly 05:00, the 05:00 firing is the one being acted on;
        # the next is tomorrow's.
        self.assertEqual(fires('0 5 * * *', D(2026, 10, 5, 5, 0), 1), [D(2026, 10, 6, 5)])

    def test_lists_ranges_and_steps(self):
        self.assertEqual(fires('15,45 9-10 * * *', D(2026, 1, 1), 4),
                         [D(2026, 1, 1, 9, 15), D(2026, 1, 1, 9, 45),
                          D(2026, 1, 1, 10, 15), D(2026, 1, 1, 10, 45)])
        self.assertEqual(fires('5/20 0 * * *', D(2026, 1, 1), 3),
                         [D(2026, 1, 1, 0, 5), D(2026, 1, 1, 0, 25), D(2026, 1, 1, 0, 45)])

    def test_weekday_counts_sunday_as_zero_and_seven(self):
        # 2026-10-11 is a Sunday.
        self.assertEqual(fires('0 4 * * 0', D(2026, 10, 5), 1), [D(2026, 10, 11, 4)])
        self.assertEqual(fires('0 4 * * 7', D(2026, 10, 5), 1), [D(2026, 10, 11, 4)])

    def test_both_day_fields_restricted_means_either(self):
        # The 1st of the month, or any Monday: 2026-10-05 is a Monday.
        self.assertEqual(fires('0 0 1 * 1', D(2026, 10, 2), 3),
                         [D(2026, 10, 5), D(2026, 10, 12), D(2026, 10, 19)])

    def test_month_rollover_and_macros(self):
        self.assertEqual(fires('@monthly', D(2026, 12, 15), 2), [D(2027, 1, 1), D(2027, 2, 1)])
        self.assertEqual(fires('@daily', D(2026, 2, 28, 12), 1), [D(2026, 3, 1)])

    def test_rejects_what_it_cannot_read(self):
        for bad in ('', '* * * *', '60 * * * *', '* 24 * * *', '0 0 0 * *',
                    '0 0 * 13 *', '0 0 * * 8', 'a * * * *', '5-1 * * * *', '*/0 * * * *'):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    maintenance.parse_cron(bad)

    def test_a_schedule_that_never_fires_is_an_error(self):
        self.assertIsNotNone(maintenance.cron_error('0 0 30 2 *'))
        self.assertIsNone(maintenance.cron_error('0 0 29 2 *'))
        self.assertIsNone(maintenance.cron_error(''))

    def test_wall_clock_in_the_given_timezone(self):
        import zoneinfo
        athens = zoneinfo.ZoneInfo('Europe/Athens')
        moment = maintenance.next_cron(maintenance.parse_cron('0 5 * * *'),
                                       D(2026, 10, 5, 12, tzinfo=athens))
        self.assertEqual((moment.hour, moment.tzinfo), (5, athens))


class TestPolicy(unittest.TestCase):

    def test_defaults_fill_anything_missing(self):
        policy = maintenance.policy_with_defaults({'enabled': True, 'stray': 1})
        self.assertTrue(policy['enabled'])
        self.assertNotIn('stray', policy)
        self.assertEqual(policy['countdown'], maintenance.DEFAULT_COUNTDOWN)

    def test_valid_changes_are_merged(self):
        policy, errors = maintenance.validate_policy({
            'enabled': True, 'window_cron': '30 4 * * 1', 'countdown': '60, 600,30,60',
            'excluded_mods': '123 456,123', 'max_wait_hours': '12',
        })
        self.assertEqual(errors, {})
        self.assertTrue(policy['enabled'])
        self.assertEqual(policy['countdown'], [600, 60, 30])
        self.assertEqual(policy['excluded_mods'], ['123', '456'])
        self.assertEqual(policy['max_wait_hours'], 12)

    def test_an_empty_schedule_switches_it_off(self):
        policy, errors = maintenance.validate_policy({'window_cron': '  '})
        self.assertEqual(errors, {})
        self.assertEqual(policy['window_cron'], '')

    def test_errors_are_reported_per_key_and_nothing_bad_is_kept(self):
        current = maintenance.policy_with_defaults(None)
        policy, errors = maintenance.validate_policy({
            'game_check_cron': 'often', 'countdown': [0], 'max_wait_hours': -1,
            'excluded_mods': ['../etc'], 'message': 'say "hi"',
        }, current)
        self.assertEqual(set(errors), {'game_check_cron', 'countdown', 'max_wait_hours',
                                       'excluded_mods', 'message'})
        self.assertEqual(policy['game_check_cron'], current['game_check_cron'])

    def test_a_message_that_cannot_reach_the_console_is_refused(self):
        for bad in ('line\nbreak', 'back\\slash', 'x' * 250, ''):
            with self.subTest(bad=bad):
                _policy, errors = maintenance.validate_policy({'message': bad})
                self.assertIn('message', errors)


class TestGameUpdate(unittest.TestCase):

    INSTALLED = {'buildid': '100', 'branch': None, 'state_flags': 4}

    def test_newer_build_on_the_installed_branch(self):
        result = maintenance.game_update(self.INSTALLED, {
            'public': {'buildid': '101', 'timeupdated': '1700000000'},
            'unstable': {'buildid': '200'}})
        self.assertTrue(result['update_available'])
        self.assertEqual((result['branch'], result['available_build'], result['available_at']),
                         ('public', '101', 1700000000))

    def test_follows_the_installed_branch_not_public(self):
        installed = dict(self.INSTALLED, branch='unstable', buildid='200')
        result = maintenance.game_update(installed, {'public': {'buildid': '101'},
                                                     'unstable': {'buildid': '200'}})
        self.assertFalse(result['update_available'])
        self.assertEqual(result['branch'], 'unstable')

    def test_a_damaged_install_needs_updating_even_on_the_same_build(self):
        installed = dict(self.INSTALLED, state_flags=6)
        self.assertTrue(maintenance.game_update(installed, {'public': {'buildid': '100'}})
                        ['update_available'])

    def test_nothing_installed_is_not_an_update(self):
        self.assertFalse(maintenance.game_update(None, {'public': {'buildid': '1'}})
                         ['update_available'])

    def test_unknown_branch(self):
        installed = dict(self.INSTALLED, branch='gone')
        self.assertFalse(maintenance.game_update(installed, {'public': {'buildid': '101'}})
                         ['update_available'])


class TestOutdatedMods(unittest.TestCase):

    USED = {'1': ['A'], '2': ['A', 'B'], '3': ['B'], '4': ['B'], '5': ['A']}
    INSTALLED = {'1': {'timeupdated': 100}, '2': {'timeupdated': 100},
                 '3': {'timeupdated': 100}, '5': {'timeupdated': 100}}
    REMOTE = {
        '1': {'found': True, 'updated': 200, 'title': 'One'},
        '2': {'found': True, 'updated': 100, 'title': 'Two'},
        '3': {'found': True, 'updated': 300, 'title': 'Three'},
        '4': {'found': True, 'updated': 300},             # not downloaded at all
        '5': {'found': True, 'updated': 300, 'banned': True},
    }

    def test_only_newer_downloaded_and_still_published_items(self):
        outdated, held = maintenance.outdated_mods(self.USED, self.INSTALLED, self.REMOTE)
        self.assertEqual([m['id'] for m in outdated], ['1', '3'])
        self.assertEqual(held, [])
        self.assertEqual(outdated[0]['servers'], ['A'])

    def test_excluded_items_are_held_back_not_dropped(self):
        outdated, held = maintenance.outdated_mods(self.USED, self.INSTALLED, self.REMOTE,
                                                   excluded=['3'])
        self.assertEqual([m['id'] for m in outdated], ['1'])
        self.assertEqual([m['id'] for m in held], ['3'])


class TestTargets(unittest.TestCase):

    GAME = {'update_available': True, 'installed_build': '1', 'available_build': '2'}

    def test_merge_keeps_the_newest_of_everything(self):
        merged = maintenance.merge_targets(
            {'game': self.GAME, 'mods': [{'id': '1', 'updated_at': 5}, {'id': '2', 'updated_at': 5}]},
            {'game': dict(self.GAME, available_build='3'), 'mods': [{'id': '1', 'updated_at': 9}]})
        self.assertEqual(merged['game']['available_build'], '3')
        self.assertEqual({m['id']: m['updated_at'] for m in merged['mods']}, {'1': 9, '2': 5})

    def test_merge_does_not_drop_the_game_for_a_mods_only_find(self):
        merged = maintenance.merge_targets({'game': self.GAME, 'mods': []},
                                           {'game': None, 'mods': [{'id': '1'}]})
        self.assertIs(merged['game'], self.GAME)

    def test_covered_by_a_cancelled_run(self):
        cancelled = {'game': self.GAME, 'mods': [{'id': '1', 'updated_at': 5}]}
        self.assertTrue(maintenance.covered_by(cancelled, {'game': self.GAME, 'mods': []}))
        self.assertTrue(maintenance.covered_by(cancelled, {'game': None,
                                                           'mods': [{'id': '1', 'updated_at': 5}]}))
        # Newer information is planned as usual.
        self.assertFalse(maintenance.covered_by(cancelled, {'game': dict(self.GAME, available_build='3'),
                                                            'mods': []}))
        self.assertFalse(maintenance.covered_by(cancelled, {'game': None,
                                                            'mods': [{'id': '1', 'updated_at': 6}]}))
        self.assertFalse(maintenance.covered_by(cancelled, {'game': None, 'mods': [{'id': '2'}]}))

    def test_automatic_targets_leave_out_what_needs_approval(self):
        game = {'result': self.GAME}
        mods = {'result': {'outdated': [{'id': '1'}], 'held_back': [{'id': '2'}]}}
        policy = maintenance.policy_with_defaults(None)
        targets = maintenance.automatic_targets(game, mods, policy)
        self.assertEqual((targets['game'], targets['mods']), (self.GAME, []))
        policy.update(game_requires_approval=True, mods_requires_approval=False)
        targets = maintenance.automatic_targets(game, mods, policy)
        self.assertEqual((targets['game'], targets['mods']), (None, [{'id': '1'}]))

    def test_selection_only_accepts_what_the_check_reported(self):
        game = {'result': self.GAME}
        mods = {'result': {'outdated': [{'id': '1'}], 'held_back': [{'id': '2'}]}}
        targets = maintenance.select_targets(game, mods, True, ['1', '2', '999'])
        self.assertEqual(targets['game'], self.GAME)
        self.assertEqual([m['id'] for m in targets['mods']], ['1', '2'])
        targets = maintenance.select_targets({'result': {'update_available': False}}, mods, True, [])
        self.assertFalse(maintenance.has_targets(targets))


class TestDecideScheduled(unittest.TestCase):

    NOW = D(2026, 10, 5, 12)

    def decide(self, players=3, window=False, force_at=None, deadline=None, **policy):
        merged = maintenance.policy_with_defaults(policy)
        return maintenance.decide_scheduled(force_at, deadline, players, window, merged, self.NOW)[0]

    def test_waits_while_people_play_and_nothing_forces_it(self):
        self.assertEqual(self.decide(), 'wait')

    def test_goes_straight_down_when_everybody_is_gone(self):
        self.assertEqual(self.decide(players=0), 'stop')

    def test_empty_does_not_count_when_the_policy_says_so(self):
        self.assertEqual(self.decide(players=0, apply_when_empty=False), 'wait')
        self.assertEqual(self.decide(players=0, apply_when_empty=False, window=True), 'stop')

    def test_window_and_deadline_force_a_countdown(self):
        self.assertEqual(self.decide(window=True), 'countdown')
        self.assertEqual(self.decide(deadline=self.NOW), 'countdown')
        self.assertEqual(self.decide(deadline=self.NOW + datetime.timedelta(seconds=1)), 'wait')

    def test_staff_asking_for_now(self):
        self.assertEqual(self.decide(force_at=self.NOW), 'countdown')
        self.assertEqual(self.decide(players=0, force_at=self.NOW, apply_when_empty=False), 'stop')


class TestCountdown(unittest.TestCase):

    STEPS = [900, 600, 300, 30, 15, 5]

    def test_format(self):
        self.assertEqual(maintenance.format_duration(900), '15 minutes')
        self.assertEqual(maintenance.format_duration(60), '1 minute')
        self.assertEqual(maintenance.format_duration(90), '1 minute 30 seconds')
        self.assertEqual(maintenance.format_duration(3600), '1 hour')
        self.assertEqual(maintenance.format_duration(5), '5 seconds')

    def test_render(self):
        self.assertEqual(maintenance.render_message('Restart in {time}.', 300),
                         'Restart in 5 minutes.')
        self.assertEqual(maintenance.broadcast_command('Restart in 5 minutes.'),
                         'servermsg "Restart in 5 minutes."')

    def test_each_warning_once_in_order(self):
        sent, said = [], []
        remaining = 900.0
        while remaining > 0:
            say, sent = maintenance.due_announcement(self.STEPS, remaining, sent)
            if say:
                said.append(say)
            remaining -= 1
        self.assertEqual(said, self.STEPS)

    def test_late_warnings_collapse_into_the_latest_with_the_real_time(self):
        say, sent = maintenance.due_announcement(self.STEPS, 100.0, [900])
        self.assertEqual(say, 100)
        self.assertEqual(sent, [900, 600, 300])
        say, _sent = maintenance.due_announcement(self.STEPS, 100.0, sent)
        self.assertIsNone(say)


class TestWorkshopManifest(unittest.TestCase):

    def test_reads_installed_items(self):
        parsed = {'AppWorkshop': {'appid': '108600', 'WorkshopItemsInstalled': {
            '2392709985': {'size': '1024', 'timeupdated': '1700000000', 'manifest': 'x'},
            'junk': {'timeupdated': '1'},
            '123': 'not a block',
        }}}
        self.assertEqual(steam.parse_workshop_manifest(parsed),
                         {'2392709985': {'timeupdated': 1700000000, 'size': 1024}})

    def test_shapes_it_does_not_understand(self):
        self.assertEqual(steam.parse_workshop_manifest({}), {})
        self.assertEqual(steam.parse_workshop_manifest(None), {})
        self.assertEqual(steam.parse_workshop_manifest({'AppWorkshop': {}}), {})


if __name__ == '__main__':
    unittest.main()

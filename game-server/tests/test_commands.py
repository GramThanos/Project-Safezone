"""Tests for the safe console-command builders (command-injection boundary)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import commands  # noqa: E402


class TestItemCommand(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(
            commands.build_item_command('Alice', 'Base.Axe', 2),
            'additem "Alice" "Base.Axe" 2'
        )

    def test_default_count(self):
        self.assertEqual(
            commands.build_item_command('Bob', 'Base.Hammer'),
            'additem "Bob" "Base.Hammer" 1'
        )

    def test_rejects_bad_username(self):
        for bad in ['Alice; quit', 'Alice\nquit', 'bad name', '', 'a' * 33, 'a"b']:
            with self.assertRaises(commands.CommandError):
                commands.build_item_command(bad, 'Base.Axe', 1)

    def test_rejects_bad_item(self):
        for bad in ['Base.Axe"; rm', 'bad item', '', 'x' * 65, 'a;b']:
            with self.assertRaises(commands.CommandError):
                commands.build_item_command('Alice', bad, 1)

    def test_rejects_bad_count(self):
        for bad in [0, -1, 101, 'x', None]:
            with self.assertRaises(commands.CommandError):
                commands.build_item_command('Alice', 'Base.Axe', bad)


class TestParseRewardCommands(unittest.TestCase):
    def _types(self, steps):
        return [s['type'] for s in steps]

    def test_single_command(self):
        steps = commands.parse_reward_commands('additem "{{USERNAME}}" "Base.Axe" 1')
        self.assertEqual(steps, [{'type': 'command', 'text': 'additem "{{USERNAME}}" "Base.Axe" 1'}])

    def test_newline_and_semicolon_separators(self):
        steps = commands.parse_reward_commands('startrain 50\nstoprain; save')
        self.assertEqual([s.get('text') for s in steps], ['startrain 50', 'stoprain', 'save'])

    def test_blank_segments_ignored(self):
        steps = commands.parse_reward_commands('\n\nsave;;\n  ;\n')
        self.assertEqual(steps, [{'type': 'command', 'text': 'save'}])

    def test_sleep_and_wait_are_steps(self):
        steps = commands.parse_reward_commands('save\nsleep 0.5\nwait 2\nstoprain')
        self.assertEqual(self._types(steps), ['command', 'sleep', 'sleep', 'command'])
        self.assertEqual(steps[1]['seconds'], 0.5)
        self.assertEqual(steps[2]['seconds'], 2.0)

    def test_leading_slash_stripped(self):
        steps = commands.parse_reward_commands('/save')
        self.assertEqual(steps, [{'type': 'command', 'text': 'save'}])

    def test_rejects_empty(self):
        for bad in ['', '   ', '\n\n', None, 123]:
            with self.assertRaises(commands.CommandError):
                commands.parse_reward_commands(bad)

    def test_rejects_only_sleeps(self):
        with self.assertRaises(commands.CommandError):
            commands.parse_reward_commands('sleep 1\nwait 2')

    def test_rejects_control_chars(self):
        with self.assertRaises(commands.CommandError):
            commands.parse_reward_commands('save\x00quit')

    def test_rejects_sleep_out_of_range(self):
        for bad in ['sleep 0', 'wait 31', 'sleep 100', 'sleep 30.1']:
            with self.assertRaises(commands.CommandError):
                commands.parse_reward_commands(bad + '\nsave')

    def test_rejects_total_sleep_over_cap(self):
        with self.assertRaises(commands.CommandError):
            commands.parse_reward_commands('save\n' + '\n'.join(['sleep 30'] * 5))

    def test_rejects_too_many_steps(self):
        with self.assertRaises(commands.CommandError):
            commands.parse_reward_commands('\n'.join(['save'] * (commands.REWARD_MAX_STEPS + 1)))

    def test_rejects_overlong_command(self):
        with self.assertRaises(commands.CommandError):
            commands.parse_reward_commands('save ' + 'x' * commands.REWARD_MAX_COMMAND_LEN)


class TestRenderCommand(unittest.TestCase):
    def test_substitutes_username(self):
        self.assertEqual(
            commands.render_command('additem "{{USERNAME}}" "Base.Axe" 1', 'Alice'),
            'additem "Alice" "Base.Axe" 1'
        )

    def test_case_and_spacing_tolerant(self):
        self.assertEqual(commands.render_command('godmode "{{ username }}" -true', 'Bob'),
                         'godmode "Bob" -true')

    def test_server_wide_needs_no_username(self):
        self.assertEqual(commands.render_command('stoprain'), 'stoprain')

    def test_rejects_placeholder_without_valid_username(self):
        for bad in [None, '', 'bad name', 'Alice; quit', 'a"b', 'a' * 33]:
            with self.assertRaises(commands.CommandError):
                commands.render_command('godmode "{{USERNAME}}" -true', bad)


class TestRewardRequiresOnline(unittest.TestCase):
    def test_targeted_when_placeholder_present(self):
        steps = commands.parse_reward_commands('additem "{{USERNAME}}" "Base.Axe" 1')
        self.assertTrue(commands.reward_requires_online(steps))

    def test_server_wide_when_no_placeholder(self):
        steps = commands.parse_reward_commands('startrain 50\nsleep 1\nstoprain')
        self.assertFalse(commands.reward_requires_online(steps))


class TestBundles(unittest.TestCase):
    def test_parses_refs_and_counts(self):
        self.assertEqual(
            commands.parse_bundles([{'ref': 7, 'count': 5}, {'ref': 9, 'count': 10}], 'item'),
            [(7, 5), (9, 10)])

    def test_a_usable_bundle_runs_once_whatever_its_count(self):
        self.assertEqual(commands.parse_bundles([{'ref': 1, 'count': 4}], 'usable'), [(1, 1)])

    def test_rejects_malformed_bundles(self):
        for bad in [None, [], 'x', [1], [{'ref': 'a'}], [{'ref': True}], [{'ref': 1, 'count': 0}],
                    [{'ref': 1, 'count': commands.MAX_COUNT + 1}], [{'ref': 1, 'count': 2.5}],
                    [{'ref': 1}, {'ref': 1}]]:
            with self.assertRaises(commands.CommandError, msg=repr(bad)):
                commands.parse_bundles(bad, 'item')

    def test_caps_how_many_bundles_one_task_carries(self):
        items = [{'ref': i} for i in range(commands.BUNDLE_MAX + 1)]
        with self.assertRaises(commands.CommandError):
            commands.parse_bundles(items, 'item')
        commands.parse_bundles(items[:commands.BUNDLE_MAX], 'item')
        usables = [{'ref': i} for i in range(commands.USABLE_BUNDLE_MAX + 1)]
        with self.assertRaises(commands.CommandError):
            commands.parse_bundles(usables, 'usable')

    def test_packs_whole_bundles_under_the_line_cap(self):
        lines = commands.pack_item_bundles([(1, 40), (2, 40), (3, 40), (4, 100), (5, 1)], limit=100)
        self.assertEqual(lines, [[(1, 40), (2, 40)], [(3, 40)], [(4, 100)], [(5, 1)]])

    def test_never_splits_a_bundle_and_never_overfills_a_line(self):
        bundles = [(i, (i * 37) % 100 + 1) for i in range(20)]
        lines = commands.pack_item_bundles(bundles)
        self.assertEqual([b for line in lines for b in line], bundles)
        for line in lines:
            self.assertLessEqual(sum(c for _, c in line), commands.MAX_COUNT)


if __name__ == '__main__':
    unittest.main()

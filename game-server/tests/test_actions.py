"""Tests for the whitelisted console action catalog."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import actions  # noqa: E402
import commands  # noqa: E402


class TestCatalogShape(unittest.TestCase):
    def test_every_action_is_well_formed(self):
        for action in actions.catalog():
            with self.subTest(action=action['id']):
                self.assertTrue(action['label'])
                self.assertTrue(action['command'])
                self.assertIn(action['min_role'], (actions.ROLE_MODERATOR, actions.ROLE_ADMIN))
                self.assertIn(action['category'], [c for c, _ in actions.CATEGORIES])
                for spec in action['params']:
                    self.assertIn(spec['type'], actions.PARAM_TYPES)
                    if spec['type'] == 'enum':
                        self.assertTrue(spec.get('options'))

    def test_catalog_is_json_safe(self):
        # The builder callable must never be serialised to the API.
        for action in actions.catalog():
            self.assertNotIn('build', action)

    def test_droppable_filter(self):
        droppable = {a['id'] for a in actions.catalog(droppable_only=True)}
        self.assertIn('god_mode', droppable)
        self.assertNotIn('ban_user', droppable)

    def test_every_droppable_action_builds_with_its_defaults(self):
        """Defaults must be enough for anything without required parameters."""
        for action in actions.catalog(droppable_only=True):
            required = [p['name'] for p in action['params'] if p.get('required')]
            if required:
                continue
            with self.subTest(action=action['id']):
                self.assertTrue(actions.build(action['id'], 'Alice'))


class TestBuilders(unittest.TestCase):
    def test_teleport_to_beacon(self):
        self.assertEqual(
            actions.build('teleport_to_beacon', 'Alice', {'destination': 'BeaconMall'}),
            'teleportplayer "Alice" "BeaconMall"'
        )

    def test_god_mode_flag(self):
        self.assertEqual(actions.build('god_mode', 'Alice', {'enabled': True}),
                         'godmode "Alice" -true')
        self.assertEqual(actions.build('god_mode', 'Alice', {'enabled': False}),
                         'godmode "Alice" -false')

    def test_grant_xp(self):
        self.assertEqual(
            actions.build('grant_xp', 'Alice', {'perk': 'Woodwork', 'amount': 250}),
            'addxp "Alice" Woodwork=250'
        )

    def test_item_defaults_count(self):
        self.assertEqual(
            actions.build('give_item', 'Alice', {'item_id': 'Base.FirstAidKit'}),
            'additem "Alice" "Base.FirstAidKit" 1'
        )

    def test_optional_parts_are_omitted(self):
        self.assertEqual(actions.build('kick', None, {'username': 'Bob'}), 'kickuser "Bob"')
        self.assertEqual(
            actions.build('kick', None, {'username': 'Bob', 'reason': 'afk'}),
            'kickuser "Bob" -r "afk"'
        )

    def test_ban_flags(self):
        self.assertEqual(
            actions.build('ban_user', None, {'username': 'Bob', 'ban_ip': True, 'reason': 'spawn kill'}),
            'banuser "Bob" -ip -r "spawn kill"'
        )

    def test_server_wide_action_needs_no_username(self):
        self.assertEqual(actions.build('stop_rain', None), 'stoprain')


class TestValidation(unittest.TestCase):
    def test_unknown_action(self):
        with self.assertRaises(commands.CommandError):
            actions.build('rm_rf', 'Alice')

    def test_rejects_bad_username(self):
        for bad in ['Alice; quit', 'Alice\nquit', 'bad name', 'a"b', 'a' * 33]:
            with self.assertRaises(commands.CommandError):
                actions.build('god_mode', bad)

    def test_rejects_injection_in_text_param(self):
        for bad in ['hi" \n quit', 'say "hello"', 'back\\slash']:
            with self.assertRaises(commands.CommandError):
                actions.build('broadcast', None, {'message': bad})

    def test_rejects_out_of_range_int(self):
        for bad in [0, 101, 'x']:
            with self.assertRaises(commands.CommandError):
                actions.build('start_rain', None, {'intensity': bad})

    def test_rejects_unknown_param(self):
        with self.assertRaises(commands.CommandError):
            actions.build('stop_rain', None, {'sudo': 'yes'})

    def test_rejects_missing_required_param(self):
        with self.assertRaises(commands.CommandError):
            actions.build('teleport_to_beacon', 'Alice', {})

    def test_rejects_invalid_enum(self):
        with self.assertRaises(commands.CommandError):
            actions.build('grant_xp', 'Alice', {'perk': 'Hacking', 'amount': 1})

    def test_rejects_invalid_ip(self):
        with self.assertRaises(commands.CommandError):
            actions.build('ban_ip', None, {'ip': '999.1.1.1'})

    def test_staff_action_refused_for_loot(self):
        with self.assertRaises(commands.CommandError):
            actions.build('ban_user', None, {'username': 'Bob'}, droppable_only=True)
        # ...but allowed on the staff path.
        self.assertEqual(actions.build('ban_user', None, {'username': 'Bob'}), 'banuser "Bob"')


class TestCommandsFacade(unittest.TestCase):
    def test_build_action_command(self):
        self.assertEqual(
            commands.build_action_command('Alice', 'give_item', {'item_id': 'Base.Axe', 'count': 2}),
            'additem "Alice" "Base.Axe" 2'
        )

    def test_requires_online(self):
        self.assertTrue(commands.action_requires_online('god_mode'))
        self.assertFalse(commands.action_requires_online('start_storm'))
        # Unknown ids fall back to the safe answer.
        self.assertTrue(commands.action_requires_online('nope'))


if __name__ == '__main__':
    unittest.main()

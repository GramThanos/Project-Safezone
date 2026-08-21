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


if __name__ == '__main__':
    unittest.main()

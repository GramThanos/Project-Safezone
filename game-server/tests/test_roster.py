"""Tests for parsing the PZ `players` console output."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import roster  # noqa: E402


class TestRoster(unittest.TestCase):
    def test_basic_block(self):
        text = 'some log\nPlayers connected (2):\n-Alice\n-Bob\nOther line'
        self.assertEqual(roster.parse_online_players(text), ['Alice', 'Bob'])

    def test_zero_players(self):
        self.assertEqual(roster.parse_online_players('Players connected (0): '), [])

    def test_no_block_returns_none(self):
        self.assertIsNone(roster.parse_online_players('random log\nno roster here'))

    def test_last_block_wins(self):
        text = ('Players connected (1):\n-Stale\nnoise\n'
                'Players connected (2):\n-Carol\n-Dave\n')
        self.assertEqual(roster.parse_online_players(text), ['Carol', 'Dave'])


if __name__ == '__main__':
    unittest.main()

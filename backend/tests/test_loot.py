"""Tests for loot box size selection and reward drawing."""
import os
import sys
import random
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'utils'))
import loot  # noqa: E402


class TestLoot(unittest.TestCase):
    def test_draw_counts(self):
        self.assertEqual(loot.draw_count('small'), 1)
        self.assertEqual(loot.draw_count('medium'), 2)
        self.assertEqual(loot.draw_count('big'), 3)

    def test_size_distribution(self):
        rng = random.Random(42)
        counts = {'small': 0, 'medium': 0, 'big': 0}
        n = 50000
        for _ in range(n):
            counts[loot.pick_box_size(rng)] += 1
        self.assertAlmostEqual(counts['small'] / n, 0.6, delta=0.02)
        self.assertAlmostEqual(counts['medium'] / n, 0.3, delta=0.02)
        self.assertAlmostEqual(counts['big'] / n, 0.1, delta=0.02)

    def test_draw_without_replacement(self):
        rng = random.Random(1)
        drawn = loot.draw_rewards([1, 2, 3, 4, 5], 3, rng)
        self.assertEqual(len(drawn), 3)
        self.assertEqual(len(set(drawn)), 3)  # distinct when pool is large enough

    def test_draw_with_replacement_when_pool_small(self):
        self.assertEqual(loot.draw_rewards([7], 3, random.Random(1)), [7, 7, 7])

    def test_empty_pool(self):
        self.assertEqual(loot.draw_rewards([], 2, random.Random(1)), [])


if __name__ == '__main__':
    unittest.main()

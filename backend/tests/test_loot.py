"""Tests for weighted box selection and reward drawing."""
import os
import sys
import random
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'utils'))
import loot  # noqa: E402


class TestLoot(unittest.TestCase):
    def test_pick_weighted_distribution(self):
        rng = random.Random(42)
        entries = [('small', 0.6), ('medium', 0.3), ('big', 0.1)]
        counts = {'small': 0, 'medium': 0, 'big': 0}
        n = 50000
        for _ in range(n):
            counts[loot.pick_weighted(entries, rng)] += 1
        self.assertAlmostEqual(counts['small'] / n, 0.6, delta=0.02)
        self.assertAlmostEqual(counts['medium'] / n, 0.3, delta=0.02)
        self.assertAlmostEqual(counts['big'] / n, 0.1, delta=0.02)

    def test_pick_weighted_ignores_zero_and_empty(self):
        self.assertEqual(loot.pick_weighted([(1, 0), (2, 0)]), None)
        self.assertEqual(loot.pick_weighted([]), None)
        # A single positive-weight entry always wins.
        self.assertEqual(loot.pick_weighted([(1, 0), (2, 5)]), 2)

    def test_draw_without_replacement(self):
        rng = random.Random(1)
        drawn = loot.draw_rewards([1, 2, 3, 4, 5], 3, rng)
        self.assertEqual(len(drawn), 3)
        self.assertEqual(len(set(drawn)), 3)  # distinct when pool is large enough

    def test_draw_with_replacement_when_pool_small(self):
        self.assertEqual(loot.draw_rewards([7], 3, random.Random(1)), [7, 7, 7])

    def test_empty_pool(self):
        self.assertEqual(loot.draw_rewards([], 2, random.Random(1)), [])

    def test_draw_weighted_skips_zero_weight(self):
        rng = random.Random(3)
        drawn = loot.draw_weighted([(1, 0), (2, 5)], 4, rng)
        self.assertTrue(all(rid == 2 for rid in drawn))

    def test_odds_sum_to_one(self):
        probs = dict(loot.odds([(1, 1), (2, 1), (3, 2)]))
        self.assertAlmostEqual(sum(probs.values()), 1.0)
        self.assertAlmostEqual(probs[3], 0.5)


if __name__ == '__main__':
    unittest.main()

"""Loot box configuration and pure drawing logic.

Box sizes are fixed config: each grants a weighted chance on daily login and draws
a number of rewards from its admin-configured pool when opened.
"""
import random

# size -> {draws: rewards given on open, weight: daily-grant probability}
BOX_SIZES = {
    'small': {'draws': 1, 'weight': 0.6},
    'medium': {'draws': 2, 'weight': 0.3},
    'big': {'draws': 3, 'weight': 0.1},
}
SIZE_ORDER = ['small', 'medium', 'big']


def pick_box_size(rng=random):
    """Pick a box size by weighted random (small 0.6 / medium 0.3 / big 0.1)."""
    r = rng.random()
    cumulative = 0.0
    for size in SIZE_ORDER:
        cumulative += BOX_SIZES[size]['weight']
        if r < cumulative:
            return size
    return SIZE_ORDER[-1]


def draw_count(size):
    """How many rewards a box of this size yields when opened."""
    return BOX_SIZES.get(size, {}).get('draws', 0)


def draw_rewards(pool_ids, n, rng=random):
    """Draw ``n`` reward ids from ``pool_ids``.

    Without replacement when the pool is large enough, otherwise with replacement
    so a small pool can still fill the box.
    """
    if not pool_ids or n <= 0:
        return []
    if len(pool_ids) >= n:
        return rng.sample(list(pool_ids), n)
    return [rng.choice(list(pool_ids)) for _ in range(n)]

"""Pure loot logic: which box you get, and what comes out of it.

Deliberately free of database access. The box configuration is *passed in* rather
than read here, so this module stays testable without a stack and the same
functions serve both the built-in defaults and an operator's tuned values.

`src/utils/box_types.py` is what reads the configured types; these defaults are
the seed for that table and the fallback if it cannot be read.
"""
import random

# size -> {draws: rewards given on open, weight: daily-grant probability}
#
# `bonus` carries weight 0 and is deliberately absent from the daily roll: it is
# only granted by the weekly streak job. It still needs a loot pool of its own,
# which is why it is a size rather than a special case.
DEFAULT_TYPES = {
    'small': {'draws': 1, 'weight': 0.6, 'label': 'Small'},
    'medium': {'draws': 2, 'weight': 0.3, 'label': 'Medium'},
    'big': {'draws': 3, 'weight': 0.1, 'label': 'Big'},
    'bonus': {'draws': 4, 'weight': 0.0, 'label': 'Weekly bonus'},
}

# Kept for callers that only need the set of known sizes.
BOX_SIZES = DEFAULT_TYPES

# The daily roll considers these, in this order.
SIZE_ORDER = ['small', 'medium', 'big']


def _resolve(types):
    return types if types else DEFAULT_TYPES


def daily_candidates(types=None):
    """Sizes eligible for the daily roll: known, active, and with weight above zero."""
    types = _resolve(types)
    return [size for size in types
            if types[size].get('weight', 0) > 0 and types[size].get('active', True)]


def pick_box_size(rng=random, types=None):
    """Pick a size by weight. Falls back to the smallest candidate."""
    types = _resolve(types)
    # Preserve the documented order where it applies, then append anything new
    # an operator has added, so tuning stays predictable.
    candidates = [s for s in SIZE_ORDER if s in daily_candidates(types)]
    candidates += [s for s in daily_candidates(types) if s not in candidates]
    if not candidates:
        return SIZE_ORDER[0]

    total = sum(types[s]['weight'] for s in candidates)
    if total <= 0:
        return candidates[0]

    r = rng.random() * total
    cumulative = 0.0
    for size in candidates:
        cumulative += types[size]['weight']
        if r < cumulative:
            return size
    return candidates[-1]


def draw_count(size, types=None):
    """How many rewards a box of this size yields when opened."""
    return _resolve(types).get(size, {}).get('draws', 0)


def draw_rewards(pool_ids, n, rng=random):
    """Draw ``n`` reward ids from ``pool_ids``, every id equally likely.

    Without replacement when the pool is large enough, otherwise with replacement
    so a small pool can still fill the box.
    """
    if not pool_ids or n <= 0:
        return []
    if len(pool_ids) >= n:
        return rng.sample(list(pool_ids), n)
    return [rng.choice(list(pool_ids)) for _ in range(n)]


def draw_weighted(entries, n, rng=random):
    """Draw ``n`` reward ids from ``[(reward_id, weight)]``.

    Weight is relative, not a percentage: a reward at 10 is ten times as likely
    as one at 1. Weight 0 means "in the pool but never drops", which is a useful
    way to retire something without deleting it and losing the history.

    Same replacement rule as `draw_rewards`: distinct picks while the pool is
    big enough, otherwise repeats so a small pool still fills the box.
    """
    pool = [(rid, float(weight or 0)) for rid, weight in entries]
    pool = [(rid, weight) for rid, weight in pool if weight > 0]
    if not pool or n <= 0:
        return []

    allow_repeats = len(pool) < n
    drawn = []
    for _ in range(n):
        total = sum(weight for _, weight in pool)
        if total <= 0:
            break
        r = rng.random() * total
        cumulative = 0.0
        chosen = len(pool) - 1
        for index, (_, weight) in enumerate(pool):
            cumulative += weight
            if r < cumulative:
                chosen = index
                break
        drawn.append(pool[chosen][0])
        if not allow_repeats:
            pool.pop(chosen)
    return drawn


def odds(entries):
    """``[(reward_id, probability)]`` for a single draw, for player-facing disclosure."""
    pool = [(rid, float(weight or 0)) for rid, weight in entries]
    pool = [(rid, weight) for rid, weight in pool if weight > 0]
    total = sum(weight for _, weight in pool)
    if total <= 0:
        return []
    return [(rid, weight / total) for rid, weight in pool]

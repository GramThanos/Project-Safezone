"""Pure loot logic: which box an event grants, and what comes out of it.

Deliberately free of database access. The box/event configuration is *passed in*
rather than read here, so this module stays testable without a stack.
"""
import random


def pick_weighted(entries, rng=random):
    """Pick one id from ``[(id, weight)]`` by weight. Returns ``None`` if empty.

    Weight is relative, not a percentage. Entries at or below zero weight are
    ignored - that is how a box stays attached to an event without being rolled.
    Used to choose which box an event grants.
    """
    pool = [(cid, float(weight or 0)) for cid, weight in entries]
    pool = [(cid, weight) for cid, weight in pool if weight > 0]
    if not pool:
        return None

    total = sum(weight for _, weight in pool)
    r = rng.random() * total
    cumulative = 0.0
    for cid, weight in pool:
        cumulative += weight
        if r < cumulative:
            return cid
    return pool[-1][0]


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

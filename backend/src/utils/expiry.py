"""Deadlines for loot that was never collected.

Kept apart from the models so the retention settings are read in exactly one
place, and so a deadline can be computed without a database session.

A setting of 0 means "never expires", which is the default: expiry is a
retention lever an operator opts into, not something imposed on a new server.
"""
from datetime import datetime, timedelta

from src.utils import settings


def _deadline(setting_key):
    try:
        days = settings.get(setting_key) or 0
    except Exception:
        # A settings failure must not silently stamp everything as expiring.
        return None
    if days <= 0:
        return None
    return datetime.utcnow() + timedelta(days=days)


def box_deadline():
    """When a box granted now should expire, or None."""
    return _deadline('box_expiry_days')


def inventory_deadline():
    """When a reward won now should expire if never sent, or None."""
    return _deadline('inventory_expiry_days')


def is_expired(row, now=None):
    """Whether a row carrying `expires_at` is past it."""
    deadline = getattr(row, 'expires_at', None)
    if deadline is None:
        return False
    return deadline <= (now or datetime.utcnow())

"""Reading the configured loot box types.

Cached briefly like the settings layer: consulted on every daily grant and every
box open, changed rarely. A read failure falls back to the built-in defaults
rather than breaking the economy.
"""
import logging
import time

from src.database import db
from src.models.box_type import BoxType
from src.utils import loot

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 15
_cache = {'types': None, 'at': 0.0}


def reset_cache():
    _cache['types'] = None
    _cache['at'] = 0.0


def all_types():
    """``{size: {draws, weight, label, active}}``, falling back to the defaults."""
    now = time.monotonic()
    if _cache['types'] is not None and now - _cache['at'] < _CACHE_TTL_SECONDS:
        return _cache['types']

    try:
        with db.get_db() as session:
            rows = session.query(BoxType).all()
            types = {
                row.size: {
                    'draws': row.draws,
                    'weight': row.weight,
                    'label': row.label or row.size.title(),
                    'active': bool(row.active),
                }
                for row in rows
            }
    except Exception as e:
        logger.error(f"Could not read box types, using defaults: {e}")
        return _cache['types'] or loot.DEFAULT_TYPES

    if not types:
        # Nothing configured yet (a fresh database before seeding).
        return loot.DEFAULT_TYPES

    _cache['types'] = types
    _cache['at'] = now
    return types


def seed(session):
    """Create any missing type from the defaults. Idempotent."""
    existing = {row.size for row in session.query(BoxType).all()}
    added = []
    for size, spec in loot.DEFAULT_TYPES.items():
        if size in existing:
            continue
        session.add(BoxType(size=size, label=spec.get('label', size.title()),
                            draws=spec['draws'], weight=spec['weight'], active=True))
        added.append(size)
    if added:
        reset_cache()
    return added

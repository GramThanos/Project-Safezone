"""The daily reset boundary for once-per-day grants.

"Today" follows the **primary game server's** timezone rather than UTC, so the
daily loot box resets when players experience a new day.

The primary server is the one flagged `is_primary`. Failing that we fall back to
the lowest-id server with a `timezone` set, which is how this worked before the
flag existed; with none set, or the game-server unreachable, the boundary stays
UTC.
"""
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from src.utils.game_server import gs_request

logger = logging.getLogger(__name__)

UTC = ZoneInfo('UTC')

# The server list changes rarely and this is read on every daily claim, so the
# resolved zone is cached briefly rather than re-fetched per request.
_CACHE_TTL_SECONDS = 300
_cache = {'zone': None, 'at': 0.0}


def primary_timezone():
    """The timezone that defines the daily reset, defaulting to UTC."""
    now = time.monotonic()
    if _cache['zone'] is not None and now - _cache['at'] < _CACHE_TTL_SECONDS:
        return _cache['zone']

    zone = UTC
    payload, status = gs_request('GET', '/api/servers')
    if status != 200:
        logger.warning("Could not read servers for the daily reset timezone; using UTC")
    else:
        servers = sorted(payload.get('data') or [], key=lambda s: s.get('id') or 0)

        # An explicitly designated primary wins; otherwise fall back to the old
        # rule so an existing deployment keeps the boundary it already had.
        primary = next((s for s in servers if s.get('is_primary')), None)
        candidates = [primary] if primary else servers

        for server in candidates:
            name = (server.get('timezone') or '').strip()
            if not name:
                continue
            try:
                zone = ZoneInfo(name)
            except Exception as e:
                logger.warning(f"Server {server.get('id')} has an unusable timezone "
                               f"'{name}' ({e}); using UTC")
            break

    _cache['zone'] = zone
    _cache['at'] = now
    return zone


def today():
    """Today's date at the daily reset boundary."""
    return datetime.now(primary_timezone()).date()


def reset_cache():
    """Forget the cached timezone (used by tests, and after a server edit)."""
    _cache['zone'] = None
    _cache['at'] = 0.0

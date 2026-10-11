"""The leaderboard: every living character on a server, ranked by zombie kills.

Read from the server's ``players.db`` through the manager, as of the game's last
save - so it lists characters whether or not anybody has linked them. Two rules
hold it together:

  * **The character, never the account.** The manager hands over each
    character's owning username so exclusions can be applied here; a public
    row is cut down to an allowlist (`PUBLIC_FIELDS`) that does not include it,
    nor the linked account.
  * **Who is left out is decided here, per request.** The cache holds the raw
    save, not a filtered board, so an exclusion or a ban takes effect on the
    next read rather than when the cache next expires.

Who may read it at all is `leaderboard_visibility`: public, signed-in players,
or disabled - staff only, from the admin panel.
"""
import logging
import re
import time

from src.utils import settings
from src.utils.game_server import gs_request
from src.utils.redis_utils import cache_get, cache_set

logger = logging.getLogger(__name__)

# The game writes players.db when it saves - every few minutes at best - so
# asking more often than this would only re-read the same save.
FRESH_SECONDS = 60
# How long a last-known board may stand in for a game-server that cannot answer.
KEEP_SECONDS = 24 * 3600
FETCH_TIMEOUT = 10

PUBLIC = 'public'
AUTHENTICATED = 'authenticated'
DISABLED = 'disabled'

# What a player's browser sees of a character. An allowlist, so a field added
# to the manager's row never reaches the public by default.
PUBLIC_FIELDS = ('name', 'profession', 'zombie_kills', 'survivor_kills',
                 'hours_survived', 'time_alive')

HIDDEN_EXCLUDED = 'excluded'
HIDDEN_BANNED = 'banned'


def visibility():
    """The effective visibility. Anything unrecognised reads as disabled."""
    try:
        value = str(settings.get('leaderboard_visibility') or '').strip().lower()
    except Exception as e:
        logger.error(f'Could not read the leaderboard visibility: {e}')
        return DISABLED
    return value if value in settings.LEADERBOARD_VISIBILITIES else DISABLED


def excluded_names(text):
    """The excluded usernames, lower-cased. One per line; commas work too."""
    return {name.lower() for name in re.split(r'[\s,]+', text or '') if name}


def cache_key(server_id):
    return f'leaderboard:{int(server_id)}'


def fetch(server_id, now=None):
    """``(entry, status)`` for one server's living characters.

    ``entry`` is ``{'characters', 'saved_at', 'fetched_at', 'stale'}`` on
    success, ``{'error'}`` otherwise. The rows are raw - pass them through
    `rank` before showing them to anybody.
    """
    now = time.time() if now is None else now
    key = cache_key(server_id)
    cached = cache_get(key)
    if cached and now - cached.get('fetched_at', 0) < FRESH_SECONDS:
        return dict(cached, stale=False), 200

    payload, status = gs_request('GET', f'/api/servers/{int(server_id)}/leaderboard',
                                 timeout=FETCH_TIMEOUT)
    if status == 200 and isinstance(payload, dict) and isinstance(payload.get('data'), dict):
        data = payload['data']
        entry = {'characters': data.get('characters') or [], 'saved_at': data.get('saved_at'),
                 'fetched_at': now}
        cache_set(key, entry, KEEP_SECONDS)
        return dict(entry, stale=False), 200

    error = (payload or {}).get('error') if isinstance(payload, dict) else None
    if status == 404:
        # A server that has never saved anybody: an empty board, not a fault.
        entry = {'characters': [], 'saved_at': None, 'fetched_at': now}
        cache_set(key, entry, KEEP_SECONDS)
        return dict(entry, stale=False), 200

    if cached:
        logger.warning(f'Leaderboard for server {server_id} unavailable ({status}: {error}); '
                       f'serving the copy from {cached.get("fetched_at")}')
        return dict(cached, stale=True), 200

    return {'error': error or 'The leaderboard is unavailable right now'}, 503


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def sort_key(row):
    """Most zombie kills first, then longest alive, then by name."""
    return (-_number(row.get('zombie_kills')), -_number(row.get('hours_survived')),
            (row.get('name') or '').lower())


def rank(characters, excluded=(), banned=(), accounts=None):
    """Every character, sorted, each marked with why it is hidden (or not).

    ``excluded`` and ``banned`` are lower-cased usernames: ``excluded`` matches
    the in-game owner or the linked account's username, ``banned`` the in-game
    owner. ``accounts`` maps a lower-cased in-game username to its linked
    account (``{'id', 'username'}``). Visible rows are numbered from 1; tied
    kills share a rank. Staff read this whole; `public_rows` cuts it down.
    """
    accounts = accounts or {}
    excluded = set(excluded)
    banned = set(banned)
    rows = []
    for character in sorted(characters, key=sort_key):
        owner = (character.get('username') or '').lower()
        account = accounts.get(owner)
        if owner in excluded or (account and account['username'].lower() in excluded):
            hidden = HIDDEN_EXCLUDED
        elif owner in banned:
            hidden = HIDDEN_BANNED
        else:
            hidden = None
        rows.append(dict(character, account=account, hidden=hidden, rank=None))

    position, previous, shown = 0, None, 0
    for row in rows:
        if row['hidden']:
            continue
        shown += 1
        kills = _number(row.get('zombie_kills'))
        if kills != previous:
            position, previous = shown, kills
        row['rank'] = position
    return rows


def public_rows(rows):
    """The visible rows, cut to what anybody may see of a character."""
    return [dict({field: row.get(field) for field in PUBLIC_FIELDS}, rank=row['rank'])
            for row in rows if not row['hidden']]

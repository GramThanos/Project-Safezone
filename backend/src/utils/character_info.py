"""A linked character's saved game data: fetched, cached, and cut to its reader.

The game-server reads ``players.db`` and hands over everything it decodes. This
module decides what of it reaches a browser, and keeps a copy in Redis so a
page of character cards does not turn into a file read per card.

**What a reader sees is an allowlist.** `owner_view` and `staff_view` copy named
fields out of the report; anything not named here never leaves the backend, so
a field the decoder learns to read later stays private until somebody decides
otherwise. Never on the list: the Steam ID, admin and cheat flags, the chat tag,
appearance and raw mod data.

**Zombie infection is staff-only.** In the game a player does not know they are
infected until the symptoms show; telling them on the website would be a cheat.
That covers the infection flag, the per-part ``zombie infection`` condition,
the infection stats and the body's infection level - and an injury that only
existed because of the infection is dropped rather than shown empty, since an
unexplained wound would say the same thing.

**The cache stores the raw report and cuts on the way out**, so a change to
the allowlist applies to the next request rather than after the copies expire.
A copy is fresh for `FRESH_SECONDS`; after that the game-server is asked again,
and if it cannot answer (down, restarting, unreadable file) the last
copy is served marked ``stale`` for up to `KEEP_SECONDS`.
"""
import logging
import time
from urllib.parse import quote

from src.utils.game_server import gs_request
from src.utils.redis_utils import cache_get, cache_set

logger = logging.getLogger(__name__)

# The game writes players.db when it saves a character - every few minutes at
# best - so asking more often than this would only re-read the same save.
FRESH_SECONDS = 60
# How long a last-known copy may stand in for a game-server that cannot answer.
KEEP_SECONDS = 24 * 3600
# A character the game has not saved yet. Short, so the first save shows soon.
MISSING_SECONDS = 30
FETCH_TIMEOUT = 5

# Stats a player can read off their own moodles in the game. Build 42 names;
# the Build 41 names that differ are included so an older save still shows them.
OWNER_STATS = ('hunger', 'thirst', 'fatigue', 'endurance', 'stress', 'panic', 'boredom',
               'unhappiness', 'pain', 'sickness', 'wetness', 'temperature', 'anger',
               'intoxication', 'drunkenness', 'fear')
INFECTION_STATS = ('zombie_infection', 'zombie_fever')
INFECTION_CONDITION = 'zombie infection'
# Conditions that are treatment, not harm: a part with only these is not injured.
TREATMENTS = ('bandaged', 'stitched', 'splint')


def cache_key(server_id, username):
    return f'charinfo:{server_id}:{(username or "").lower()}'


def fetch(server_id, username, now=None):
    """``(entry, status)`` for one linked character.

    ``entry`` is ``{'report', 'saved_at', 'fetched_at', 'stale'}`` on success,
    ``{'error'}`` otherwise. The report is raw - pass it through a view.
    """
    now = time.time() if now is None else now
    key = cache_key(server_id, username)
    cached = cache_get(key)

    if cached and now - cached.get('fetched_at', 0) < FRESH_SECONDS:
        if 'report' in cached:
            return dict(cached, stale=False), 200
        if now - cached.get('fetched_at', 0) < MISSING_SECONDS:
            return {'error': cached.get('error')}, 404

    payload, status = gs_request(
        'GET', f'/api/servers/{int(server_id)}/characters/{quote(username, safe="")}',
        timeout=FETCH_TIMEOUT)

    if status == 200 and isinstance(payload, dict) and isinstance(payload.get('data'), dict):
        data = payload['data']
        entry = {'report': data.get('character') or {}, 'saved_at': data.get('saved_at'),
                 'fetched_at': now}
        cache_set(key, entry, KEEP_SECONDS)
        return dict(entry, stale=False), 200

    error = (payload or {}).get('error') if isinstance(payload, dict) else None
    if status == 404:
        # Authoritative: the save has no such character (any more). A kept copy
        # would describe somebody who is not there, so it is replaced.
        cache_set(key, {'error': error, 'fetched_at': now}, KEEP_SECONDS)
        return {'error': error or 'This character has not been saved yet'}, 404

    if cached and 'report' in cached:
        logger.warning(f'Character data for {username}@{server_id} unavailable '
                       f'({status}: {error}); serving the copy from {cached.get("fetched_at")}')
        return dict(cached, stale=True), 200

    return {'error': error or 'Character data is unavailable right now'}, 503


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _stat(entry):
    if not isinstance(entry, dict) or _number(entry.get('value')) is None:
        return None
    out = {'value': entry['value']}
    if _number(entry.get('percent')) is not None:
        out['percent'] = entry['percent']
    return out


def _injuries(health, staff):
    out = []
    for injury in health.get('injuries') or []:
        if not isinstance(injury, dict):
            continue
        conditions = [c for c in injury.get('conditions') or [] if isinstance(c, str)]
        if not staff:
            conditions = [c for c in conditions if c != INFECTION_CONDITION]
            health_value = _number(injury.get('health'))
            harmed = (health_value is not None and health_value < 100) or any(
                c not in TREATMENTS for c in conditions)
            if not harmed:
                continue
        out.append({'part': injury.get('part'), 'health': _number(injury.get('health')),
                    'conditions': conditions})
    return out


def _view(report, staff):
    report = report if isinstance(report, dict) else {}
    character = report.get('character') or {}
    status = report.get('status') or {}
    location = report.get('location') or {}
    health = report.get('health') or {}
    condition = report.get('condition') or {}
    stats = condition.get('stats') or {}
    nutrition = condition.get('nutrition') or {}
    perks = (report.get('skills') or {}).get('perks') or {}
    decoding = report.get('decoding') or {}

    view = {
        'name': character.get('name'),
        'gender': character.get('gender'),
        'profession': character.get('profession'),
        'traits': [t for t in character.get('traits') or [] if isinstance(t, str)],
        'status': status.get('status'),
        'hours_survived': _number(status.get('hours_survived')),
        'time_alive': status.get('time_alive'),
        'days_survived': _number(status.get('days_survived')),
        'zombie_kills': _number(status.get('zombie_kills')),
        'survivor_kills': _number(status.get('survivor_kills')),
        'asleep': bool(status.get('asleep')),
        'in_vehicle': bool(status.get('in_vehicle')),
        'location': {
            'x': _number(location.get('x')),
            'y': _number(location.get('y')),
            'z': _number(location.get('z')),
            'text': location.get('location'),
            'facing': location.get('facing'),
        },
        'skills': {
            name: {'level': _number(p.get('level')) or 0, 'xp': _number(p.get('xp')) or 0}
            for name, p in perks.items() if isinstance(p, dict)
        },
        'injuries': _injuries(health, staff),
        'stats': {name: _stat(stats[name]) for name in OWNER_STATS if _stat(stats.get(name))},
        'weight': _number(nutrition.get('weight')),
        'complete': bool(decoding.get('complete')),
    }

    if staff:
        body = health.get('body') or {}
        parts = health.get('body_parts') or []
        view['infection'] = {
            'infected': bool(status.get('zombie_infected') or health.get('zombie_infected')),
            'parts': [p.get('name') for p in parts if isinstance(p, dict) and p.get('infected')],
            'level': _number(body.get('infection_level')),
            'stats': {name: _stat(stats[name]) for name in INFECTION_STATS if _stat(stats.get(name))},
        }
    return view


def owner_view(report):
    """What the character's own account may see."""
    return _view(report, staff=False)


def staff_view(report):
    """What moderators and admins see: the owner's view plus the infection."""
    return _view(report, staff=True)


def respond(entry, view):
    """The JSON body for a successful `fetch`, through ``view``."""
    return {
        'character': view(entry.get('report')),
        'saved_at': entry.get('saved_at'),
        'fetched_at': entry.get('fetched_at'),
        'stale': bool(entry.get('stale')),
    }


def unlinked(saved, linked_usernames):
    """The saved characters no account is linked to, in save order.

    ``saved`` is a server's character summaries (each with the owning
    ``username``); ``linked_usernames`` the in-game usernames linked on that
    server. Compared without case, as the database's collation compares them
    when a claim checks for an existing link.
    """
    linked = {(name or '').lower() for name in linked_usernames}
    return [c for c in saved
            if c.get('username') and c['username'].lower() not in linked]

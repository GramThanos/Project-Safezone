#!/usr/bin/env python3
"""Community loot-box configurations, fetched from GitHub.

Why this lives in the manager and not the backend
-------------------------------------------------
Same reason as the item catalog (:mod:`items`): the backend sits on the compose
`internal` network (``internal: true``) with no egress and no DNS, so it cannot
reach GitHub. This container already needs the internet for SteamCMD, so the one
place with egress stays the one place with egress, and the backend proxies.

Where the data comes from
-------------------------
A directory of JSON files published in the project repo under
``community/reward-boxes/``:

* ``list.json``  - an index: ``{"schema": ..., "boxes": [{id, name, ...}]}``
* ``<id>.json``  - one box config: name, description, and a list of rewards
                   each carrying its full definition plus a drop weight.

The config is *applied* by the backend (create missing rewards, set pool
weights); this module only fetches and caches the raw JSON. It does not trust
the content - the backend re-validates every field before anything is written,
exactly as it does for a hand-authored reward.

Caching
-------
The index is cached in Redis with a TTL and served stale on a failed refresh,
the same shape as the item catalog: a slightly old list beats an empty one.
Individual configs are small and fetched on demand when an admin previews one,
so they are not cached.

Uses ``urllib`` rather than ``requests``, like :mod:`items` and :mod:`workshop` -
this image pins a small dependency set and this needs one GET.
"""
import datetime
import json
import re
import time
import urllib.error
import urllib.request

import config
import cache


def _log(message):
    ts = datetime.datetime.now().isoformat()
    print(f"[{ts}][RewardBoxes] {message}")


CACHE_KEY = 'reward_boxes:list'
LOCK_KEY = 'reward_boxes:list:refreshing'
LOCK_SECONDS = 30

# A box id is a bare slug, so it can only ever name a sibling file in the
# published directory - never traverse out of it or reach another host.
BOX_ID_RE = re.compile(r'^[a-z0-9-]{1,64}$')

_USER_AGENT = ('Project-Safezone/1.0 (self-hosted Project Zomboid server '
               'manager; reward boxes; '
               'https://github.com/gramthanos/Project-Safezone)')


def _fetch_json(url):
    """GET a URL and parse it as JSON. Returns ``(payload, error)``."""
    request = urllib.request.Request(
        url,
        headers={'User-Agent': _USER_AGENT, 'Accept': 'application/json'},
        method='GET',
    )
    try:
        with urllib.request.urlopen(request, timeout=config.REWARD_BOXES_TIMEOUT) as response:
            text = response.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        return None, f'GitHub returned HTTP {e.code}'
    except urllib.error.URLError as e:
        return None, f'Could not reach GitHub: {e.reason}'
    except (TimeoutError, OSError) as e:
        return None, f'Could not reach GitHub: {e}'

    try:
        return json.loads(text), None
    except (json.JSONDecodeError, TypeError) as e:
        return None, f'The config was fetched but is not valid JSON: {e}'


def _read_cache():
    raw = cache.get_value(CACHE_KEY)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _claim_refresh():
    """True if this request should be the one to go and fetch."""
    r = cache.get_instance()
    if not r:
        return True
    try:
        return bool(r.set(LOCK_KEY, '1', nx=True, ex=LOCK_SECONDS))
    except Exception:
        return True


def get_box_list(force=False):
    """The community box index. Returns ``(payload, error)``.

    Served from cache whenever there is one, even when a refresh failed - an
    hour-old list beats no list. ``error`` is set when the *refresh* failed, so
    the panel can say the list may be out of date without pretending it is empty.
    """
    cached = _read_cache()

    fresh_enough = (
        cached
        and not force
        and (time.time() - cached.get('fetched_at', 0)) < config.REWARD_BOXES_TTL
    )
    if fresh_enough:
        return cached, None

    # Somebody else is already fetching; their result will be along shortly.
    if cached and not force and not _claim_refresh():
        return cached, None

    payload, error = _fetch_json(config.REWARD_BOXES_BASE_URL + 'list.json')
    if error:
        if cached:
            _log(f'Refresh failed, serving the cached copy: {error}')
            return cached, error
        _log(f'Could not fetch the box list: {error}')
        return None, error

    boxes = payload.get('boxes') if isinstance(payload, dict) else None
    if not isinstance(boxes, list):
        return (cached, error) if cached else (None, 'The box list is malformed')

    result = {
        'boxes': boxes,
        'fetched_at': int(time.time()),
        'source': config.REWARD_BOXES_BASE_URL + 'list.json',
    }
    cache.set_value(CACHE_KEY, json.dumps(result), ttl=config.REWARD_BOXES_TTL * 4)
    _log(f'Box list refreshed: {len(boxes)} boxes')
    return result, None


def get_box(box_id):
    """One box config by id. Returns ``(payload, error)``.

    Fetched on demand, not cached: configs are small and only read when an admin
    previews one. The id is validated as a bare slug first, so it can only ever
    resolve to a file inside the published directory.
    """
    if not box_id or not BOX_ID_RE.match(box_id):
        return None, 'invalid box id'
    payload, error = _fetch_json(config.REWARD_BOXES_BASE_URL + f'{box_id}.json')
    if error:
        return None, error
    if not isinstance(payload, dict) or not isinstance(payload.get('rewards'), list):
        return None, 'The box config is malformed'
    return payload, None

#!/usr/bin/env python3
"""Community server-config templates, fetched from GitHub.

Why this lives in the manager and not the backend
-------------------------------------------------
Same reason as the reward boxes (:mod:`reward_boxes`) and the item catalog
(:mod:`items`): the backend sits on the compose `internal` network with no egress,
so it cannot reach GitHub. This container already needs the internet for SteamCMD,
so the one place with egress stays the one place with egress, and the backend
proxies.

Where the data comes from
-------------------------
A directory of JSON files published in the project repo under
``community/server-templates/``:

* ``list.json``  - an index: ``{"schema": ..., "templates": [{id, name, ...}]}``
* ``<id>.json``  - one combined template:
                   ``{name, description, settings: {...}, sandbox: {...}}``, where
                   ``settings`` is a flat map of Project Zomboid INI keys and
                   ``sandbox`` a flat map of SandboxVars keys (either half may be
                   omitted). Applied to the ``.ini`` and ``_SandboxVars.lua``
                   respectively.

A template is *applied* to a server's INI by the game-server
(:mod:`server_config`), which re-filters every key through a blacklist before a
byte is written - ports, credentials and per-server identity can never be applied
however the template was authored. This module only fetches and caches the raw
JSON; it does not trust the content.

Caching mirrors the reward boxes: the index is cached in Redis with a TTL and
served stale on a failed refresh - a slightly old list beats an empty one.
Individual templates are small and fetched on demand when an admin previews one.

Uses ``urllib`` rather than ``requests``, like :mod:`reward_boxes`, :mod:`items`
and :mod:`workshop` - this image pins a small dependency set and this needs one
GET.
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
    print(f"[{ts}][ServerTemplates] {message}")


CACHE_KEY = 'server_templates:list'
LOCK_KEY = 'server_templates:list:refreshing'
LOCK_SECONDS = 30

# A template id is a bare slug, so it can only ever name a sibling file in the
# published directory - never traverse out of it or reach another host.
TEMPLATE_ID_RE = re.compile(r'^[a-z0-9-]{1,64}$')

_USER_AGENT = ('Project-Safezone/1.0 (self-hosted Project Zomboid server '
               'manager; server templates; '
               'https://github.com/gramthanos/Project-Safezone)')


def _fetch_json(url):
    """GET a URL and parse it as JSON. Returns ``(payload, error)``."""
    request = urllib.request.Request(
        url,
        headers={'User-Agent': _USER_AGENT, 'Accept': 'application/json'},
        method='GET',
    )
    try:
        with urllib.request.urlopen(request, timeout=config.SERVER_TEMPLATES_TIMEOUT) as response:
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
        return None, f'The template was fetched but is not valid JSON: {e}'


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


def get_template_list(force=False):
    """The community template index. Returns ``(payload, error)``.

    Served from cache whenever there is one, even when a refresh failed - an
    hour-old list beats no list. ``error`` is set when the *refresh* failed, so
    the panel can say the list may be out of date without pretending it is empty.
    """
    cached = _read_cache()

    fresh_enough = (
        cached
        and not force
        and (time.time() - cached.get('fetched_at', 0)) < config.SERVER_TEMPLATES_TTL
    )
    if fresh_enough:
        return cached, None

    # Somebody else is already fetching; their result will be along shortly.
    if cached and not force and not _claim_refresh():
        return cached, None

    payload, error = _fetch_json(config.SERVER_TEMPLATES_BASE_URL + 'list.json')
    if error:
        if cached:
            _log(f'Refresh failed, serving the cached copy: {error}')
            return cached, error
        _log(f'Could not fetch the template list: {error}')
        return None, error

    templates = payload.get('templates') if isinstance(payload, dict) else None
    if not isinstance(templates, list):
        return (cached, error) if cached else (None, 'The template list is malformed')

    result = {
        'templates': templates,
        'fetched_at': int(time.time()),
        'source': config.SERVER_TEMPLATES_BASE_URL + 'list.json',
    }
    cache.set_value(CACHE_KEY, json.dumps(result), ttl=config.SERVER_TEMPLATES_TTL * 4)
    _log(f'Template list refreshed: {len(templates)} templates')
    return result, None


def get_template(template_id):
    """One template by id. Returns ``(payload, error)``.

    Fetched on demand, not cached: templates are small and only read when an
    admin previews one. The id is validated as a bare slug first, so it can only
    ever resolve to a file inside the published directory.
    """
    if not template_id or not TEMPLATE_ID_RE.match(template_id):
        return None, 'invalid template id'
    payload, error = _fetch_json(config.SERVER_TEMPLATES_BASE_URL + f'{template_id}.json')
    if error:
        return None, error
    # A combined template carries an INI ``settings`` map and/or a ``sandbox``
    # map; at least one must be a present object for it to be applicable.
    if not isinstance(payload, dict) or not (
            isinstance(payload.get('settings'), dict)
            or isinstance(payload.get('sandbox'), dict)):
        return None, 'The template is malformed'
    return payload, None

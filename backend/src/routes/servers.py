"""Public server status routes (proxied to the game-server API)"""
import logging
from flask import Blueprint, jsonify, request
from src.utils.game_server import gs_request
from src.utils.redis_utils import (apply_live_state, get_online_players,
                                   cache_get, cache_set)
from src.middleware.auth import token_required, current_user_optional

logger = logging.getLogger(__name__)
servers_bp = Blueprint('servers', __name__, url_prefix='/api/servers')

# These endpoints are public and polled by every visitor, and each one is a
# network round-trip to the game-server. The upstream data changes slowly (the
# server *list*) or is a slow aggregation (the activity history), so it is cached
# briefly in Redis. Live runtime state and online counts are NOT cached here -
# they come from Redis keys the orchestrator writes (see `apply_live_state` /
# `get_online_players`), so a start/stop still shows immediately.
_SERVERS_CACHE_KEY = 'cache:gs:servers'
_SERVERS_TTL = 10       # seconds
_HISTORY_TTL = 60       # seconds; the chart buckets by the minute, so this is plenty


def _server_list():
    """The game-server's server list, cached briefly.

    Returns ``(data, error, status)`` - ``data`` is the raw list of server dicts
    on success (``error`` None), otherwise ``data`` is None and the caller passes
    ``error``/``status`` straight back. The cached value is the upstream payload,
    never a response already stripped by `_visible`: caching the stripped form
    would risk serving one caller's connection details to another.
    """
    cached = cache_get(_SERVERS_CACHE_KEY)
    if cached is not None:
        return cached, None, 200

    payload, status = gs_request('GET', '/api/servers')
    if status != 200:
        return None, payload.get('error', 'Failed to fetch servers'), status

    data = payload.get('data', [])
    cache_set(_SERVERS_CACHE_KEY, data, _SERVERS_TTL)
    return data, None, 200

# Where to connect. Shown to members, withheld from anonymous visitors - the
# server list is a public advert, but the address is for people who signed up.
CONNECTION_FIELDS = ('hostname', 'ports')

# Never served from this blueprint, to anybody, signed in or not.
#
# RCON is the server's remote console. No player-facing feature uses the port,
# and it was previously grouped with the connection details - so any account
# that had existed for thirty seconds was handed the exact port to point an
# RCON brute-forcer at. The password itself was never at risk (`to_dict` only
# emits it under `include_sensitive`, which no response path sets); this closes
# the reconnaissance half. Staff read both through the admin server views,
# which proxy the game-server API directly and do not come through here.
STAFF_ONLY_FIELDS = ('rcon_port',)


def _visible(servers):
    """Strip whatever this caller may not see.

    Done here rather than only in the browser: a field the page hides is still
    a field the endpoint hands to anyone who asks for it directly, which is not
    a restriction at all.
    """
    hidden = set(STAFF_ONLY_FIELDS)
    if not current_user_optional():
        hidden.update(CONNECTION_FIELDS)
    return [{k: v for k, v in server.items() if k not in hidden}
            for server in servers]


def _with_online(servers):
    """Attach how many players are on each server right now.

    Public, unlike the connection details and unlike the roster itself: "is
    anyone playing" is the question the server list exists to answer, and a
    count gives that away without naming anybody. The names stay behind
    `/api/servers/:id/online`, which requires a token.
    """
    for server in servers:
        try:
            server['online_count'] = len(get_online_players(server['id']))
        except Exception as e:
            # A count is a nicety; failing to read one must not fail the list.
            logger.error(f"Online count error for server {server.get('id')}: {e}")
            server['online_count'] = None
    return servers


@servers_bp.route('', methods=['GET'])
def get_all_servers():
    """Get all servers (public endpoint; connection details need a sign-in)"""
    data, error, status = _server_list()
    if error:
        return jsonify({'error': error}), status
    return jsonify({'servers': _visible(data)}), 200


@servers_bp.route('/<int:server_id>', methods=['GET'])
def get_server(server_id):
    """Get specific server (public endpoint; connection details need a sign-in)"""
    payload, status = gs_request('GET', f'/api/servers/{server_id}')
    if status != 200:
        return jsonify({'error': payload.get('error', 'Server not found')}), status
    return jsonify({'server': _visible([payload.get('data') or {}])[0]}), 200


@servers_bp.route('/status', methods=['GET'])
def get_servers_status():
    """All servers with their live runtime state (public endpoint).

    Connection details need a sign-in; the name, description, state and player
    activity are open, because that is what the page is for.
    """
    data, error, status = _server_list()
    if error:
        return jsonify({'error': error}), status

    servers = _with_online(apply_live_state(data))
    return jsonify({'servers': _visible(servers)}), 200


@servers_bp.route('/<int:server_id>/history', methods=['GET'])
def get_server_history(server_id):
    """Online-player history for a server, for the activity chart (public).

    Defaults to the last 24 hours.
    """
    # Coerced to whole numbers before they reach the cache key, so a caller
    # cannot mint unbounded distinct keys with junk query strings, and the
    # forwarded params are what the game-server expects anyway.
    try:
        hours = int(request.args.get('hours', 24))
    except (TypeError, ValueError):
        hours = 24
    bucket = None
    if request.args.get('bucket_minutes'):
        try:
            bucket = int(request.args.get('bucket_minutes'))
        except (TypeError, ValueError):
            bucket = None

    cache_key = f"cache:gs:history:{server_id}:{hours}:{bucket if bucket else ''}"
    cached = cache_get(cache_key)
    if cached is not None:
        return jsonify({'history': cached}), 200

    params = {'hours': hours}
    if bucket:
        params['bucket_minutes'] = bucket

    payload, status = gs_request('GET', f'/api/servers/{server_id}/history', params=params)
    if status != 200:
        return jsonify({'error': payload.get('error', 'Failed to fetch server history')}), status

    data = payload.get('data', [])
    cache_set(cache_key, data, _HISTORY_TTL)
    return jsonify({'history': data}), 200


@servers_bp.route('/<int:server_id>/online', methods=['GET'])
@token_required
def get_online(current_user, server_id):
    """List the in-game usernames currently online on a server (auth required).

    Used to constrain reward delivery to players who are actually online.
    """
    online = sorted(get_online_players(server_id))
    return jsonify({'online': online}), 200

"""Public server status routes (proxied to the game-server API)"""
import logging
from flask import Blueprint, jsonify, request
from src.utils.game_server import gs_request
from src.utils.redis_utils import apply_live_state, get_online_players
from src.middleware.auth import token_required, current_user_optional

logger = logging.getLogger(__name__)
servers_bp = Blueprint('servers', __name__, url_prefix='/api/servers')

# Where to connect. Shown to members, withheld from anonymous visitors - the
# server list is a public advert, but the address is for people who signed up.
CONNECTION_FIELDS = ('hostname', 'ports', 'rcon_port')


def _visible(servers):
    """Strip the connection details unless the caller is signed in.

    Done here rather than only in the browser: a field the page hides is still
    a field the endpoint hands to anyone who asks for it directly, which is not
    a restriction at all.
    """
    if current_user_optional():
        return servers
    return [{k: v for k, v in server.items() if k not in CONNECTION_FIELDS}
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
    payload, status = gs_request('GET', '/api/servers')
    if status != 200:
        return jsonify({'error': payload.get('error', 'Failed to fetch servers')}), status
    return jsonify({'servers': _visible(payload.get('data', []))}), 200


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
    payload, status = gs_request('GET', '/api/servers')
    if status != 200:
        return jsonify({'error': payload.get('error', 'Failed to fetch servers')}), status

    servers = _with_online(apply_live_state(payload.get('data', [])))
    return jsonify({'servers': _visible(servers)}), 200


@servers_bp.route('/<int:server_id>/history', methods=['GET'])
def get_server_history(server_id):
    """Online-player history for a server, for the activity chart (public).

    Defaults to the last 24 hours.
    """
    params = {'hours': request.args.get('hours', 24)}
    if request.args.get('bucket_minutes'):
        params['bucket_minutes'] = request.args.get('bucket_minutes')

    payload, status = gs_request('GET', f'/api/servers/{server_id}/history', params=params)
    if status != 200:
        return jsonify({'error': payload.get('error', 'Failed to fetch server history')}), status
    return jsonify({'history': payload.get('data', [])}), 200


@servers_bp.route('/<int:server_id>/online', methods=['GET'])
@token_required
def get_online(current_user, server_id):
    """List the in-game usernames currently online on a server (auth required).

    Used to constrain reward delivery to players who are actually online.
    """
    online = sorted(get_online_players(server_id))
    return jsonify({'online': online}), 200

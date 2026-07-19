"""Public server status routes (proxied to the game-server API)"""
import logging
from flask import Blueprint, jsonify
from src.utils.game_server import gs_request
from src.utils.redis_utils import apply_live_state, get_online_players
from src.middleware.auth import token_required

logger = logging.getLogger(__name__)
servers_bp = Blueprint('servers', __name__, url_prefix='/api/servers')


@servers_bp.route('', methods=['GET'])
def get_all_servers():
    """Get all servers (public endpoint)"""
    payload, status = gs_request('GET', '/api/servers')
    if status != 200:
        return jsonify({'error': payload.get('error', 'Failed to fetch servers')}), status
    return jsonify({'servers': payload.get('data', [])}), 200


@servers_bp.route('/<int:server_id>', methods=['GET'])
def get_server(server_id):
    """Get specific server (public endpoint)"""
    payload, status = gs_request('GET', f'/api/servers/{server_id}')
    if status != 200:
        return jsonify({'error': payload.get('error', 'Server not found')}), status
    return jsonify({'server': payload.get('data')}), 200


@servers_bp.route('/status', methods=['GET'])
def get_servers_status():
    """Get all servers with their live runtime state (public endpoint)"""
    payload, status = gs_request('GET', '/api/servers')
    if status != 200:
        return jsonify({'error': payload.get('error', 'Failed to fetch servers')}), status

    servers = apply_live_state(payload.get('data', []))
    return jsonify({'servers': servers}), 200


@servers_bp.route('/<int:server_id>/online', methods=['GET'])
@token_required
def get_online(current_user, server_id):
    """List the in-game usernames currently online on a server (auth required).

    Used to constrain reward delivery to players who are actually online.
    """
    online = sorted(get_online_players(server_id))
    return jsonify({'online': online}), 200

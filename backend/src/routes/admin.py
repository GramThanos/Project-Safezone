"""Admin panel routes.

User management is handled locally (backend owns the `users` table). Server and
task operations are proxied to the game-server API, which owns those tables.
"""
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify
from src.database import db
from src.models.user import User
from src.models.player import Player
from src.models.claim_request import ClaimRequest
from src.models.reward import Reward
from src.models.box_loot_pool import BoxLootPool
from src.models.audit_log import AuditLog
from src.middleware.auth import moderator_required, admin_required
from src.utils.game_server import gs_request
from src.utils.redis_utils import apply_live_state
from src.utils import loot, audit

logger = logging.getLogger(__name__)
admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')

# Map control actions to the commands the orchestrator listens for.
SERVER_CONTROL_ACTIONS = {'start', 'stop', 'sleep', 'command'}


# ---------------------------------------------------------------------------
# User management (local)
# ---------------------------------------------------------------------------

@admin_bp.route('/users', methods=['GET'])
@moderator_required
def get_users(current_user):
    """Get all users (moderator/admin only)"""
    try:
        role = request.args.get('role')
        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))

        with db.get_db() as session:
            query = session.query(User)
            if role:
                query = query.filter_by(role=role)
            users = query.limit(limit).offset(offset).all()

            return jsonify({
                'users': [u.to_dict() for u in users]
            }), 200
    except Exception as e:
        logger.error(f"Get users error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/users/<int:user_id>', methods=['PUT'])
@admin_required
def update_user_role(current_user, user_id):
    """Update user role (admin only)"""
    data = request.get_json()

    if not data or 'role' not in data:
        return jsonify({'error': 'Role is required'}), 400

    if data['role'] not in User.ROLES:
        return jsonify({'error': 'Invalid role'}), 400

    try:
        with db.get_db() as session:
            user = session.query(User).filter_by(id=user_id).first()

            if not user:
                return jsonify({'error': 'User not found'}), 404

            user.role = data['role']

            return jsonify({
                'message': 'User role updated successfully',
                'user': user.to_dict()
            }), 200
    except Exception as e:
        logger.error(f"Update user role error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# Server management (proxied to the game-server API)
# ---------------------------------------------------------------------------

@admin_bp.route('/servers', methods=['GET'])
@moderator_required
def get_servers(current_user):
    """Get all servers (moderator/admin only)"""
    params = {}
    if request.args.get('limit'):
        params['limit'] = request.args.get('limit')
    if request.args.get('offset'):
        params['offset'] = request.args.get('offset')

    payload, status = gs_request('GET', '/api/servers', params=params)
    if status != 200:
        return jsonify({'error': payload.get('error', 'Failed to fetch servers')}), status
    return jsonify({'servers': apply_live_state(payload.get('data', []))}), 200


@admin_bp.route('/servers/<int:server_id>', methods=['GET'])
@moderator_required
def get_server(current_user, server_id):
    """Get a single server (moderator/admin only)"""
    payload, status = gs_request('GET', f'/api/servers/{server_id}')
    if status != 200:
        return jsonify({'error': payload.get('error', 'Server not found')}), status
    return jsonify({'server': payload.get('data')}), 200


@admin_bp.route('/servers', methods=['POST'])
@admin_required
def create_server(current_user):
    """Create new server (admin only)"""
    data = request.get_json()
    if not data or not data.get('name'):
        return jsonify({'error': 'Server name is required'}), 400

    payload, status = gs_request('POST', '/api/servers', json=data)
    if status not in (200, 201):
        return jsonify({'error': payload.get('error', 'Failed to create server')}), status
    return jsonify({
        'message': 'Server created successfully',
        'server': payload.get('data')
    }), status


@admin_bp.route('/servers/<int:server_id>', methods=['PUT'])
@admin_required
def update_server(current_user, server_id):
    """Update server (admin only)"""
    data = request.get_json() or {}

    payload, status = gs_request('PUT', f'/api/servers/{server_id}', json=data)
    if status != 200:
        return jsonify({'error': payload.get('error', 'Failed to update server')}), status
    return jsonify({
        'message': 'Server updated successfully',
        'server': payload.get('data')
    }), 200


@admin_bp.route('/servers/<int:server_id>', methods=['DELETE'])
@admin_required
def delete_server(current_user, server_id):
    """Delete server (admin only)"""
    payload, status = gs_request('DELETE', f'/api/servers/{server_id}')
    if status != 200:
        return jsonify({'error': payload.get('error', 'Failed to delete server')}), status
    return jsonify({'message': 'Server deleted successfully'}), 200


@admin_bp.route('/servers/<int:server_id>/<string:action>', methods=['POST'])
@moderator_required
def control_server(current_user, server_id, action):
    """Send a lifecycle command to a server (moderator/admin only).

    Valid actions: start, stop, sleep, command. ``command`` expects a JSON body
    with a ``command`` string that is forwarded to the running server console.
    """
    if action not in SERVER_CONTROL_ACTIONS:
        return jsonify({'error': f'Invalid action: {action}'}), 400

    body = None
    if action == 'command':
        data = request.get_json(silent=True) or {}
        if not data.get('command'):
            return jsonify({'error': 'A command string is required'}), 400
        body = {'command': data['command']}

    payload, status = gs_request('POST', f'/api/servers/{server_id}/{action}', json=body)
    if status not in (200, 202):
        return jsonify({'error': payload.get('error', 'Failed to send command')}), status
    return jsonify({'message': payload.get('message', 'Command sent successfully')}), 200


# ---------------------------------------------------------------------------
# Claim request review (account ↔ in-game player linking)
# ---------------------------------------------------------------------------

@admin_bp.route('/claims', methods=['GET'])
@moderator_required
def get_claims(current_user):
    """List claim requests (moderator/admin only)"""
    try:
        status = request.args.get('status')
        with db.get_db() as session:
            query = session.query(ClaimRequest)
            if status:
                query = query.filter_by(status=status)
            claims = query.order_by(ClaimRequest.created_at.desc()).all()
            return jsonify({'claims': [c.to_dict() for c in claims]}), 200
    except Exception as e:
        logger.error(f"Get claims error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/claims/<int:claim_id>/approve', methods=['POST'])
@moderator_required
def approve_claim(current_user, claim_id):
    """Approve a claim request and link the in-game player to the account."""
    try:
        with db.get_db() as session:
            claim = session.query(ClaimRequest).filter_by(id=claim_id).first()
            if not claim:
                return jsonify({'error': 'Claim not found'}), 404
            if claim.status != ClaimRequest.STATUS_PENDING:
                return jsonify({'error': 'Claim is not pending'}), 409

            # Guard against a race: identity already linked since the request.
            already_linked = (session.query(Player)
                              .filter_by(server_id=claim.server_id,
                                         in_game_username=claim.in_game_username,
                                         verified=True)
                              .first())
            if already_linked:
                return jsonify({'error': 'That player is already linked'}), 409

            player = Player(
                user_id=claim.user_id,
                name=claim.in_game_username,
                server_id=claim.server_id,
                in_game_username=claim.in_game_username,
                verified=True
            )
            session.add(player)
            session.flush()  # obtain player.id

            claim.status = ClaimRequest.STATUS_APPROVED
            claim.player_id = player.id
            claim.reviewed_by = current_user['user_id']
            claim.reviewed_at = datetime.utcnow()

            audit.record(session, current_user['user_id'], 'claim.approve',
                         target=f'claim:{claim_id}',
                         detail=f"linked {claim.in_game_username}@server{claim.server_id} to user {claim.user_id}")

            return jsonify({
                'message': 'Claim approved',
                'claim': claim.to_dict(),
                'player': player.to_dict()
            }), 200
    except Exception as e:
        logger.error(f"Approve claim error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/claims/<int:claim_id>/reject', methods=['POST'])
@moderator_required
def reject_claim(current_user, claim_id):
    """Reject a claim request."""
    try:
        with db.get_db() as session:
            claim = session.query(ClaimRequest).filter_by(id=claim_id).first()
            if not claim:
                return jsonify({'error': 'Claim not found'}), 404
            if claim.status != ClaimRequest.STATUS_PENDING:
                return jsonify({'error': 'Claim is not pending'}), 409

            claim.status = ClaimRequest.STATUS_REJECTED
            claim.reviewed_by = current_user['user_id']
            claim.reviewed_at = datetime.utcnow()

            audit.record(session, current_user['user_id'], 'claim.reject',
                         target=f'claim:{claim_id}',
                         detail=f"rejected {claim.in_game_username}@server{claim.server_id} for user {claim.user_id}")

            return jsonify({'message': 'Claim rejected', 'claim': claim.to_dict()}), 200
    except Exception as e:
        logger.error(f"Reject claim error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# Loot box pool configuration (which rewards each box size can contain)
# ---------------------------------------------------------------------------

@admin_bp.route('/box-pools', methods=['GET'])
@moderator_required
def get_box_pools(current_user):
    """List box loot pool entries (with reward details), optionally per size."""
    try:
        size = request.args.get('size')
        with db.get_db() as session:
            query = session.query(BoxLootPool)
            if size:
                query = query.filter_by(size=size)
            entries = query.all()
            rewards_by_id = {r.id: r for r in session.query(Reward).all()}
            result = []
            for e in entries:
                row = e.to_dict()
                reward = rewards_by_id.get(e.reward_id)
                row['reward'] = reward.to_dict() if reward else None
                result.append(row)
            return jsonify({'pools': result}), 200
    except Exception as ex:
        logger.error(f"Get box pools error: {ex}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/box-pools', methods=['POST'])
@admin_required
def add_box_pool(current_user):
    """Add a reward to a box size's loot pool (admin only)."""
    data = request.get_json() or {}
    size = data.get('size')
    reward_id = data.get('reward_id')
    if size not in loot.BOX_SIZES:
        return jsonify({'error': 'Invalid box size'}), 400
    if not reward_id:
        return jsonify({'error': 'reward_id is required'}), 400
    try:
        with db.get_db() as session:
            reward = session.query(Reward).filter_by(id=reward_id).first()
            if not reward:
                return jsonify({'error': 'Reward not found'}), 404
            existing = session.query(BoxLootPool).filter_by(size=size, reward_id=reward_id).first()
            if existing:
                return jsonify({'error': 'Reward already in this pool'}), 409
            entry = BoxLootPool(size=size, reward_id=reward_id)
            session.add(entry)
            session.flush()
            return jsonify({'message': 'Added to pool', 'pool': entry.to_dict()}), 201
    except Exception as ex:
        logger.error(f"Add box pool error: {ex}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/box-pools/<int:entry_id>', methods=['DELETE'])
@admin_required
def delete_box_pool(current_user, entry_id):
    """Remove a reward from a box loot pool (admin only)."""
    try:
        with db.get_db() as session:
            entry = session.query(BoxLootPool).filter_by(id=entry_id).first()
            if not entry:
                return jsonify({'error': 'Pool entry not found'}), 404
            session.delete(entry)
            return jsonify({'message': 'Removed from pool'}), 200
    except Exception as ex:
        logger.error(f"Delete box pool error: {ex}")
        return jsonify({'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# Reward delivery (admin direct-give)
# ---------------------------------------------------------------------------

@admin_bp.route('/give', methods=['POST'])
@moderator_required
def give_reward(current_user):
    """Give an item or usable to an online in-game player (moderator/admin only).

    Creates a give_reward delivery task on the game-server. The game-server checks
    the player is online and builds the console command safely.
    """
    data = request.get_json() or {}
    server_id = data.get('server_id')
    username = (data.get('in_game_username') or '').strip()
    kind = data.get('kind', 'item')

    if not server_id or not username:
        return jsonify({'error': 'server_id and in_game_username are required'}), 400
    try:
        server_id = int(server_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid server_id'}), 400

    payload = {'action': 'give_reward', 'server_id': server_id, 'username': username, 'kind': kind}
    if kind == 'usable':
        if not data.get('command_template'):
            return jsonify({'error': 'command_template is required for usables'}), 400
        payload['command_template'] = data['command_template']
    else:
        if not data.get('in_game_id'):
            return jsonify({'error': 'in_game_id is required for items'}), 400
        payload['in_game_id'] = data['in_game_id']
        payload['count'] = data.get('count', 1)

    resp, status = gs_request('POST', '/api/tasks', json=payload)
    if status not in (200, 201):
        return jsonify({'error': resp.get('error', 'Failed to create delivery task')}), status

    detail = (f"{kind} {payload.get('in_game_id') or payload.get('command_template')} "
              f"-> {username}@server{server_id}")
    with db.get_db() as session:
        audit.record(session, current_user['user_id'], 'reward.give', target=username, detail=detail)

    return jsonify({'message': 'Delivery task created', 'task': resp.get('data')}), status


@admin_bp.route('/audit', methods=['GET'])
@moderator_required
def get_audit_log(current_user):
    """View recent audit log entries (moderator/admin only)."""
    try:
        limit = min(int(request.args.get('limit', 100)), 500)
        with db.get_db() as session:
            entries = (session.query(AuditLog)
                       .order_by(AuditLog.created_at.desc())
                       .limit(limit)
                       .all())
            return jsonify({'entries': [e.to_dict() for e in entries]}), 200
    except Exception as e:
        logger.error(f"Get audit log error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# Task management (proxied to the game-server API)
# ---------------------------------------------------------------------------

@admin_bp.route('/tasks', methods=['GET'])
@moderator_required
def get_tasks(current_user):
    """Get all tasks from game server (moderator/admin only)"""
    params = {}
    for key in ('status', 'limit', 'offset'):
        if request.args.get(key):
            params[key] = request.args.get(key)

    payload, status = gs_request('GET', '/api/tasks', params=params)
    if status != 200:
        return jsonify({'error': payload.get('error', 'Failed to fetch tasks')}), status
    # Normalize the game-server's {data: [...]} envelope to {tasks: [...]}.
    return jsonify({'tasks': payload.get('data', [])}), 200


@admin_bp.route('/tasks', methods=['POST'])
@moderator_required
def create_task(current_user):
    """Create new task on game server (moderator/admin only)"""
    data = request.get_json()

    if not data or not data.get('action'):
        return jsonify({'error': 'Task action is required'}), 400

    payload, status = gs_request('POST', '/api/tasks', json=data)
    if status not in (200, 201):
        return jsonify({'error': payload.get('error', 'Failed to create task')}), status
    return jsonify({
        'message': 'Task created successfully',
        'task': payload.get('data')
    }), status

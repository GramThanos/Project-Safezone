"""Account-side claim request routes.

An account claims an in-game player (username on a server). The player must be
online at request time; an admin later approves the request to link it.
"""
import re
import logging
from flask import Blueprint, request, jsonify
from src.database import db
from src.models.player import Player
from src.models.claim_request import ClaimRequest
from src.middleware.auth import token_required
from src.utils.game_server import gs_request
from src.utils.redis_utils import is_player_online

logger = logging.getLogger(__name__)
claims_bp = Blueprint('claims', __name__, url_prefix='/api/claims')

# PZ in-game usernames: letters, digits, underscore, up to 32 chars.
USERNAME_RE = re.compile(r'^[A-Za-z0-9_]{1,32}$')


@claims_bp.route('', methods=['GET'])
@token_required
def get_my_claims(current_user):
    """List the current account's claim requests"""
    try:
        with db.get_db() as session:
            claims = (session.query(ClaimRequest)
                      .filter_by(user_id=current_user['user_id'])
                      .order_by(ClaimRequest.created_at.desc())
                      .all())
            return jsonify({'claims': [c.to_dict() for c in claims]}), 200
    except Exception as e:
        logger.error(f"Get claims error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@claims_bp.route('', methods=['POST'])
@token_required
def create_claim(current_user):
    """Submit a claim request for an online in-game player"""
    data = request.get_json() or {}
    server_id = data.get('server_id')
    username = (data.get('in_game_username') or '').strip()

    if not server_id or not username:
        return jsonify({'error': 'server_id and in_game_username are required'}), 400
    if not USERNAME_RE.match(username):
        return jsonify({'error': 'Invalid in-game username'}), 400
    try:
        server_id = int(server_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid server_id'}), 400

    # The server must exist (verified via the game-server API).
    _, status = gs_request('GET', f'/api/servers/{server_id}')
    if status == 404:
        return jsonify({'error': 'Server not found'}), 404
    if status != 200:
        return jsonify({'error': 'Could not verify server'}), 503

    # The target player must currently be online to prove it is real and present.
    if not is_player_online(server_id, username):
        return jsonify({'error': 'That player is not currently online on this server'}), 409

    try:
        with db.get_db() as session:
            # Block if this identity is already linked to a verified player.
            already_linked = (session.query(Player)
                              .filter_by(server_id=server_id, in_game_username=username, verified=True)
                              .first())
            if already_linked:
                return jsonify({'error': 'That player is already linked to an account'}), 409

            # Block duplicate pending requests for the same identity.
            existing = (session.query(ClaimRequest)
                        .filter_by(server_id=server_id, in_game_username=username,
                                   status=ClaimRequest.STATUS_PENDING)
                        .first())
            if existing:
                return jsonify({'error': 'A pending claim for that player already exists'}), 409

            claim = ClaimRequest(
                user_id=current_user['user_id'],
                server_id=server_id,
                in_game_username=username,
                status=ClaimRequest.STATUS_PENDING
            )
            session.add(claim)
            session.flush()
            return jsonify({
                'message': 'Claim request submitted',
                'claim': claim.to_dict()
            }), 201
    except Exception as e:
        logger.error(f"Create claim error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

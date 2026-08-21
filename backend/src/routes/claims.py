"""Account-side claim routes.

An account claims an in-game character (username on a server). The character must
be online at request time, and that *is* the proof: only someone controlling the
character can have it connected, so the link is made immediately rather than
queued for staff approval. Staff can revoke a link afterwards.
"""
import re
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify
from src.database import db
from src.models.character import Character
from src.models.claim_request import ClaimRequest
from src.models.notification import Notification
from src.middleware.auth import token_required
from src.utils.game_server import gs_request
from src.utils.redis_utils import is_player_online
from src.utils import audit, notify, alerting

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
    """Claim an online in-game character, linking it to this account."""
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

    # The target character must currently be online to prove it is real and present.
    if not is_player_online(server_id, username):
        return jsonify({'error': 'That character is not currently online on this server'}), 409

    try:
        with db.get_db() as session:
            # One account per in-game identity. This is the only real gate now
            # that approval is automatic.
            already_linked = (session.query(Character)
                              .filter_by(server_id=server_id, in_game_username=username, verified=True)
                              .first())
            if already_linked:
                return jsonify({'error': 'That character is already linked to an account'}), 409

            character = Character(
                user_id=current_user['user_id'],
                name=username,
                server_id=server_id,
                in_game_username=username,
                verified=True
            )
            session.add(character)
            session.flush()  # obtain character.id

            # The claim row is kept as the record of how the link came about.
            claim = ClaimRequest(
                user_id=current_user['user_id'],
                server_id=server_id,
                in_game_username=username,
                status=ClaimRequest.STATUS_APPROVED,
                character_id=character.id,
                reviewed_at=datetime.utcnow()
            )
            session.add(claim)
            session.flush()

            # actor None = the system decided this, not a staff member.
            audit.record(session, None, 'claim.auto_approve',
                         target=f'claim:{claim.id}',
                         detail=f"linked {username}@server{server_id} to user "
                                f"{current_user['user_id']} (online check passed)")

            notify.send(session, current_user['user_id'], Notification.KIND_CLAIM,
                        f'{username} is linked to your account',
                        body='You can send rewards to this character while it is online.',
                        link='/characters')

            alerting.emit('character.linked',
                          f'{username} is now linked to an account',
                          server_id=server_id,
                          fields=[('Character', username),
                                  ('Account', current_user.get('username'))])

            return jsonify({
                'message': 'Character linked to your account',
                'claim': claim.to_dict(),
                'character': character.to_dict()
            }), 201
    except Exception as e:
        logger.error(f"Create claim error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

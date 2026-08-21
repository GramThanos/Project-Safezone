"""Character management routes.

Characters are not created here: they come only from an approved claim request,
which proves the account actually controls the in-game character (it must be
online when claimed, and staff approves the link). This module is read/update
plus an explicit unlink.
"""
import logging
from flask import Blueprint, request, jsonify
from src.database import db
from src.models.character import Character
from src.models.claim_request import ClaimRequest
from src.middleware.auth import token_required
from src.utils import audit

logger = logging.getLogger(__name__)
characters_bp = Blueprint('characters', __name__, url_prefix='/api/characters')


@characters_bp.route('', methods=['GET'])
@token_required
def get_characters(current_user):
    """Get all characters for current user"""
    try:
        with db.get_db() as session:
            characters = session.query(Character).filter_by(user_id=current_user['user_id']).all()
            return jsonify({
                'characters': [c.to_dict() for c in characters]
            }), 200
    except Exception as e:
        logger.error(f"Get characters error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@characters_bp.route('/<int:character_id>', methods=['GET'])
@token_required
def get_character(current_user, character_id):
    """Get specific character"""
    try:
        with db.get_db() as session:
            character = session.query(Character).filter_by(id=character_id).first()

            if not character:
                return jsonify({'error': 'Character not found'}), 404

            # Check if character belongs to current user
            if character.user_id != current_user['user_id']:
                return jsonify({'error': 'Access denied'}), 403

            return jsonify({'character': character.to_dict()}), 200
    except Exception as e:
        logger.error(f"Get character error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@characters_bp.route('/<int:character_id>', methods=['PUT'])
@token_required
def update_character(current_user, character_id):
    """Update character"""
    data = request.get_json()

    try:
        with db.get_db() as session:
            character = session.query(Character).filter_by(id=character_id).first()

            if not character:
                return jsonify({'error': 'Character not found'}), 404

            # Check if character belongs to current user
            if character.user_id != current_user['user_id']:
                return jsonify({'error': 'Access denied'}), 403

            # Notes only.
            #
            # The name is not editable: it comes from the claim, and the
            # "Linked" badge on the card vouches for that identity. Letting the
            # owner rename it afterwards would let the card say one thing while
            # the verified in-game name says another, which is the one property
            # the badge exists to guarantee.
            #
            # The avatar is not editable either: it was a player-supplied URL
            # rendered as an <img> in every viewer's browser, which is an
            # arbitrary outbound request to a host of that player's choosing.
            # Both are ignored rather than rejected, so an older client that
            # still sends them gets its notes saved instead of an error.
            if 'description' in data:
                character.description = data['description']
            if 'stats' in data:
                character.set_stats(data['stats'])

            return jsonify({
                'message': 'Character updated successfully',
                'character': character.to_dict()
            }), 200
    except Exception as e:
        logger.error(f"Update character error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@characters_bp.route('/<int:character_id>', methods=['DELETE'])
@token_required
def unlink_character(current_user, character_id):
    """Unlink a character from the account, releasing the in-game identity.

    The approved claim that created the link is detached at the same time, so no
    claim is left pointing at a character that no longer exists. Once unlinked
    the identity is free: anyone may claim it again through the normal flow
    (proof of being online plus staff approval).
    """
    try:
        with db.get_db() as session:
            character = session.query(Character).filter_by(id=character_id).first()

            if not character:
                return jsonify({'error': 'Character not found'}), 404

            # Check if character belongs to current user
            if character.user_id != current_user['user_id']:
                return jsonify({'error': 'Access denied'}), 403

            was_verified = character.verified
            identity = f"{character.in_game_username}@server{character.server_id}"

            # Detach the approved claim(s) that produced this link.
            (session.query(ClaimRequest)
             .filter_by(character_id=character_id)
             .update({'character_id': None}, synchronize_session=False))

            session.delete(character)

            if was_verified:
                audit.record(session, current_user['user_id'], 'character.unlink',
                             target=character.in_game_username,
                             detail=f"released {identity}")

            return jsonify({'message': 'Character unlinked successfully'}), 200
    except Exception as e:
        logger.error(f"Unlink character error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

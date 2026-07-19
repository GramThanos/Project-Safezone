"""Admin reward catalog routes (items + usables)."""
import re
import logging
from flask import Blueprint, request, jsonify
from src.database import db
from src.models.reward import Reward
from src.middleware.auth import moderator_required, admin_required

logger = logging.getLogger(__name__)
rewards_bp = Blueprint('rewards', __name__, url_prefix='/api/admin/rewards')

ITEM_ID_RE = re.compile(r'^[A-Za-z0-9_.]{1,64}$')


def _validate_payload(data, partial=False):
    """Validate a reward payload. Returns an error string or None.

    When ``partial`` (PUT), only provided fields are checked.
    """
    if not partial:
        if not data.get('name'):
            return 'name is required'
        if data.get('kind') not in Reward.KINDS:
            return 'kind must be item or usable'

    kind = data.get('kind')
    if kind == Reward.KIND_ITEM and 'in_game_id' in data:
        if not data['in_game_id'] or not ITEM_ID_RE.match(data['in_game_id']):
            return 'invalid in_game_id'
    if kind == Reward.KIND_USABLE and 'command_template' in data:
        tmpl = data['command_template']
        if not tmpl or any(c in tmpl for c in ('\n', '\r', '\x00')):
            return 'invalid command_template'

    # On create, ensure the kind-specific field is present.
    if not partial:
        if kind == Reward.KIND_ITEM and not data.get('in_game_id'):
            return 'in_game_id is required for items'
        if kind == Reward.KIND_USABLE and not data.get('command_template'):
            return 'command_template is required for usables'
    return None


@rewards_bp.route('', methods=['GET'])
@moderator_required
def list_rewards(current_user):
    """List catalog rewards (moderator/admin), optionally filtered by kind."""
    try:
        kind = request.args.get('kind')
        with db.get_db() as session:
            query = session.query(Reward)
            if kind:
                query = query.filter_by(kind=kind)
            rewards = query.order_by(Reward.name.asc()).all()
            return jsonify({'rewards': [r.to_dict() for r in rewards]}), 200
    except Exception as e:
        logger.error(f"List rewards error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@rewards_bp.route('', methods=['POST'])
@admin_required
def create_reward(current_user):
    """Create a catalog reward (admin only)."""
    data = request.get_json() or {}
    error = _validate_payload(data)
    if error:
        return jsonify({'error': error}), 400
    try:
        with db.get_db() as session:
            reward = Reward(
                kind=data['kind'],
                name=data['name'],
                description=data.get('description', ''),
                icon=data.get('icon', ''),
                in_game_id=data.get('in_game_id') if data['kind'] == Reward.KIND_ITEM else None,
                command_template=data.get('command_template') if data['kind'] == Reward.KIND_USABLE else None,
                active=data.get('active', True)
            )
            session.add(reward)
            session.flush()
            return jsonify({'message': 'Reward created', 'reward': reward.to_dict()}), 201
    except Exception as e:
        logger.error(f"Create reward error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@rewards_bp.route('/<int:reward_id>', methods=['PUT'])
@admin_required
def update_reward(current_user, reward_id):
    """Update a catalog reward (admin only)."""
    data = request.get_json() or {}
    try:
        with db.get_db() as session:
            reward = session.query(Reward).filter_by(id=reward_id).first()
            if not reward:
                return jsonify({'error': 'Reward not found'}), 404

            # Validate against the resulting kind.
            data.setdefault('kind', reward.kind)
            error = _validate_payload(data, partial=True)
            if error:
                return jsonify({'error': error}), 400

            for field in ('kind', 'name', 'description', 'icon', 'in_game_id',
                          'command_template', 'active'):
                if field in data:
                    setattr(reward, field, data[field])
            return jsonify({'message': 'Reward updated', 'reward': reward.to_dict()}), 200
    except Exception as e:
        logger.error(f"Update reward error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@rewards_bp.route('/<int:reward_id>', methods=['DELETE'])
@admin_required
def delete_reward(current_user, reward_id):
    """Delete a catalog reward (admin only)."""
    try:
        with db.get_db() as session:
            reward = session.query(Reward).filter_by(id=reward_id).first()
            if not reward:
                return jsonify({'error': 'Reward not found'}), 404
            session.delete(reward)
            return jsonify({'message': 'Reward deleted'}), 200
    except Exception as e:
        logger.error(f"Delete reward error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

"""Admin reward catalog routes (items + usables).

A usable reward is a free-text ``commands`` sequence validated by the game-server
before it is stored, so a reward can never be saved with a sequence that would
fail at delivery time. The command text is admin-authored; the game-server is the
command boundary and re-validates the one player-influenced value (the recipient
name) when the reward is actually delivered.
"""
import logging
from flask import Blueprint, request, jsonify
from src.database import db
from src.models.reward import Reward
from src.middleware.auth import moderator_required, admin_required
from src.utils import audit, paging
from src.utils.rewards import validate_reward_payload, validate_usable_commands

logger = logging.getLogger(__name__)
rewards_bp = Blueprint('rewards', __name__, url_prefix='/api/admin/rewards')


@rewards_bp.route('', methods=['GET'])
@moderator_required
def list_rewards(current_user):
    """List catalog rewards (moderator/admin), optionally filtered by kind."""
    try:
        limit, offset = paging.params()
        kind = request.args.get('kind')
        with db.get_db() as session:
            query = session.query(Reward)
            if kind:
                query = query.filter_by(kind=kind)
            query = query.order_by(Reward.name.asc())
            rewards, total = paging.page(query, limit, offset)
            return jsonify({
                'rewards': [r.to_dict() for r in rewards],
                'pagination': paging.meta(total, limit, offset)
            }), 200
    except Exception as e:
        logger.error(f"List rewards error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@rewards_bp.route('', methods=['POST'])
@admin_required
def create_reward(current_user):
    """Create a catalog reward (admin only)."""
    data = request.get_json() or {}
    error = validate_reward_payload(data)
    if error:
        return jsonify({'error': error}), 400
    error, status = validate_usable_commands(data)
    if error:
        return jsonify({'error': error}), status
    try:
        is_usable = data['kind'] == Reward.KIND_USABLE
        with db.get_db() as session:
            reward = Reward(
                kind=data['kind'],
                name=data['name'],
                description=data.get('description', ''),
                icon=data.get('icon', ''),
                in_game_id=data.get('in_game_id') if not is_usable else None,
                commands=data.get('commands') if is_usable else None,
                active=data.get('active', True)
            )
            session.add(reward)
            session.flush()
            audit.record(session, current_user['user_id'], 'reward.create',
                         target=f'reward:{reward.id}',
                         detail=f"{reward.kind} '{reward.name}'")
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
            error = validate_reward_payload(data, partial=True)
            if error:
                return jsonify({'error': error}), 400
            # Re-validate whenever the command sequence changes.
            if 'commands' in data:
                check = dict(data)
                check.setdefault('commands', reward.commands)
                error, status = validate_usable_commands(check)
                if error:
                    return jsonify({'error': error}), status

            fields = ('kind', 'name', 'description', 'icon', 'in_game_id',
                      'commands', 'action_id', 'action_params', 'active')
            changed = [f for f in fields if f in data]
            for field in changed:
                setattr(reward, field, data[field])

            audit.record(session, current_user['user_id'], 'reward.update',
                         target=f'reward:{reward_id}',
                         detail=f"'{reward.name}' changed: {', '.join(changed) or 'nothing'}")
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
            name, kind = reward.name, reward.kind
            session.delete(reward)
            audit.record(session, current_user['user_id'], 'reward.delete',
                         target=f'reward:{reward_id}',
                         detail=f"{kind} '{name}'")
            return jsonify({'message': 'Reward deleted'}), 200
    except Exception as e:
        logger.error(f"Delete reward error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

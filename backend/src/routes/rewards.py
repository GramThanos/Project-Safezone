"""Admin reward catalog routes (items + usables).

A usable reward is a catalog action (`action_id` + `action_params`) validated by
the game-server before it is stored, so a reward can never be saved with
parameters that would fail at delivery time. Only loot-safe ("droppable")
actions may back a reward - moderation and server operations are refused here
and are reachable only through the admin give endpoint.
"""
import re
import logging
from flask import Blueprint, request, jsonify
from src.database import db
from src.models.reward import Reward
from src.middleware.auth import moderator_required, admin_required
from src.utils import audit, paging
from src.utils.actions import validate_action

logger = logging.getLogger(__name__)
rewards_bp = Blueprint('rewards', __name__, url_prefix='/api/admin/rewards')

ITEM_ID_RE = re.compile(r'^[A-Za-z0-9_.]{1,64}$')

# `count` reaches an `additem` console command, so it is bounded like any other
# parameter that crosses that boundary rather than trusted from the panel.
MAX_ITEM_COUNT = 1000


def _validate_payload(data, partial=False):
    """Validate a reward payload. Returns an error string or None.

    When ``partial`` (PUT), only provided fields are checked. Usables are
    additionally validated against the game-server action catalog by the caller
    (see ``_validate_usable_action``).
    """
    if not partial:
        if not data.get('name'):
            return 'name is required'
        if data.get('kind') not in Reward.KINDS:
            return 'kind must be item or usable'

    if 'count' in data:
        count = data['count']
        if isinstance(count, bool) or not isinstance(count, int):
            return 'count must be a whole number'
        if count < 1 or count > MAX_ITEM_COUNT:
            return f'count must be between 1 and {MAX_ITEM_COUNT}'

    kind = data.get('kind')
    if kind == Reward.KIND_ITEM and 'in_game_id' in data:
        if not data['in_game_id'] or not ITEM_ID_RE.match(data['in_game_id']):
            return 'invalid in_game_id'

    # On create, ensure the kind-specific field is present.
    if not partial:
        if kind == Reward.KIND_ITEM and not data.get('in_game_id'):
            return 'in_game_id is required for items'
        if kind == Reward.KIND_USABLE and not data.get('action_id'):
            return 'action_id is required for usables'
    return None


def _validate_usable_action(data):
    """Validate a usable's action against the catalog. Returns ``(error, status)``.

    No-op for item rewards and for legacy free-text usables.
    """
    if data.get('kind') != Reward.KIND_USABLE or not data.get('action_id'):
        return None, 200
    _action, _command, error, status = validate_action(
        data['action_id'], data.get('action_params'), droppable_only=True
    )
    return error, status


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
    error = _validate_payload(data)
    if error:
        return jsonify({'error': error}), 400
    error, status = _validate_usable_action(data)
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
                count=data.get('count', 1) if not is_usable else 1,
                action_id=data.get('action_id') if is_usable else None,
                action_params=(data.get('action_params') or {}) if is_usable else None,
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
            error = _validate_payload(data, partial=True)
            if error:
                return jsonify({'error': error}), 400
            # Re-validate whenever the action or its parameters change.
            if 'action_id' in data or 'action_params' in data:
                check = dict(data)
                check.setdefault('action_id', reward.action_id)
                check.setdefault('action_params', reward.action_params)
                error, status = _validate_usable_action(check)
                if error:
                    return jsonify({'error': error}), status

            fields = ('kind', 'name', 'description', 'icon', 'in_game_id', 'count',
                      'action_id', 'action_params', 'active')
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

"""Admin reward catalog routes (items + usables).

A usable reward is a free-text ``commands`` sequence validated by the game-server
before it is stored, so a reward can never be saved with a sequence that would
fail at delivery time. The command text is admin-authored; the game-server is the
command boundary and re-validates the one player-influenced value (the recipient
name) when the reward is actually delivered.
"""
import logging
from flask import Blueprint, request, jsonify
from sqlalchemy import or_
from src.database import db
from src.models.reward import Reward
from src.models.shop_item import ShopItem
from src.middleware.auth import moderator_required, admin_required
from src.utils import audit, coins, paging
from src.utils.rewards import validate_reward_payload, validate_usable_commands

logger = logging.getLogger(__name__)
rewards_bp = Blueprint('rewards', __name__, url_prefix='/api/admin/rewards')


@rewards_bp.route('', methods=['GET'])
@moderator_required
def list_rewards(current_user):
    """List catalog rewards (moderator/admin), optionally filtered by kind and searched.

    ``q`` matches the name, the item id and the description, so a picker can
    find "Base.Axe" by typing "axe".
    """
    try:
        limit, offset = paging.params()
        kind = request.args.get('kind')
        q = (request.args.get('q') or '').strip()[:64]
        with db.get_db() as session:
            query = session.query(Reward)
            if kind:
                query = query.filter_by(kind=kind)
            if q:
                # `!` escapes the wildcards, so a typed % or _ is matched literally.
                like = '%' + q.replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%'
                query = query.filter(or_(Reward.name.ilike(like, escape='!'),
                                         Reward.in_game_id.ilike(like, escape='!'),
                                         Reward.description.ilike(like, escape='!')))
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
                active=data.get('active', True),
                coin_value=data.get('coin_value', 1)
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

            # A shop listing may never cost less than what it sells back for,
            # so a change that would raise the sell value of something listed
            # above its price is refused rather than quietly opening a way to
            # make coins.
            if 'coin_value' in data and data['coin_value'] > (reward.coin_value or 0):
                under = _listings_under_floor(session, reward_id, data['coin_value'])
                if under:
                    return jsonify({
                        'error': 'That would make this reward sell for more than it costs in the '
                                 'shop. Raise these prices first: ' + '; '.join(under)
                    }), 409

            fields = ('kind', 'name', 'description', 'icon', 'in_game_id',
                      'commands', 'action_id', 'action_params', 'active', 'coin_value')
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


def _listings_under_floor(session, reward_id, coin_value):
    """Shop listings of this reward priced below what it would sell back for."""
    floor = max(1, coin_value)
    rows = (session.query(ShopItem)
            .filter(ShopItem.reward_id == reward_id, ShopItem.price < floor)
            .order_by(ShopItem.id.asc())
            .all())
    return [f"listing #{listing.id} (×{listing.count}) at {listing.price}, needs {floor}"
            for listing in rows]


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

"""Inventory routes: view won rewards and send/activate them for a player."""
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify
from src.database import db
from src.models.inventory_item import InventoryItem
from src.models.reward import Reward
from src.models.player import Player
from src.middleware.auth import token_required
from src.utils.game_server import gs_request
from src.utils.redis_utils import is_player_online
from src.utils import audit

logger = logging.getLogger(__name__)
inventory_bp = Blueprint('inventory', __name__, url_prefix='/api/inventory')


def _reconcile(session, item):
    """Resolve a 'sending' item's status from its game-server delivery task."""
    if item.status != InventoryItem.STATUS_SENDING or not item.task_id:
        return
    payload, status = gs_request('GET', f'/api/tasks/{item.task_id}')
    if status != 200:
        return
    task = payload.get('data') or {}
    if task.get('status') != 'completed':
        return
    result = (task.get('data') or {}).get('result')
    if result == 'success':
        item.status = InventoryItem.STATUS_DELIVERED
        item.delivered_at = datetime.utcnow()
    else:
        # Failed (e.g. player went offline) -> return to inventory to retry.
        item.status = InventoryItem.STATUS_HELD


@inventory_bp.route('', methods=['GET'])
@token_required
def list_inventory(current_user):
    """List the account's inventory with reward details."""
    try:
        with db.get_db() as session:
            items = (session.query(InventoryItem)
                     .filter_by(user_id=current_user['user_id'])
                     .order_by(InventoryItem.created_at.desc())
                     .all())
            # Reconcile any in-flight deliveries before returning.
            for item in items:
                _reconcile(session, item)

            result = []
            for item in items:
                reward = session.get(Reward, item.reward_id)
                result.append(item.to_dict(reward=reward))
            return jsonify({'inventory': result}), 200
    except Exception as e:
        logger.error(f"List inventory error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@inventory_bp.route('/<int:item_id>/send', methods=['POST'])
@token_required
def send_item(current_user, item_id):
    """Send/activate an inventory item for one of the account's online players."""
    data = request.get_json() or {}
    player_id = data.get('player_id')
    if not player_id:
        return jsonify({'error': 'player_id is required'}), 400

    try:
        with db.get_db() as session:
            item = (session.query(InventoryItem)
                    .filter_by(id=item_id, user_id=current_user['user_id'])
                    .first())
            if not item:
                return jsonify({'error': 'Inventory item not found'}), 404
            if item.status not in (InventoryItem.STATUS_HELD, InventoryItem.STATUS_FAILED):
                return jsonify({'error': 'Item is not available to send'}), 409

            player = (session.query(Player)
                      .filter_by(id=player_id, user_id=current_user['user_id'])
                      .first())
            if not player:
                return jsonify({'error': 'Player not found'}), 404
            if not player.is_deliverable():
                return jsonify({'error': 'That character is not linked/verified'}), 400
            if not is_player_online(player.server_id, player.in_game_username):
                return jsonify({'error': 'That character is not currently online'}), 409

            reward = session.get(Reward, item.reward_id)
            if not reward:
                return jsonify({'error': 'Reward no longer exists'}), 404

            payload = {
                'action': 'give_reward',
                'server_id': player.server_id,
                'username': player.in_game_username,
                'kind': reward.kind
            }
            if reward.kind == Reward.KIND_USABLE:
                payload['command_template'] = reward.command_template
            else:
                payload['in_game_id'] = reward.in_game_id
                payload['count'] = 1

            resp, status = gs_request('POST', '/api/tasks', json=payload)
            if status not in (200, 201):
                return jsonify({'error': resp.get('error', 'Failed to dispatch delivery')}), status

            task = resp.get('data') or {}
            item.status = InventoryItem.STATUS_SENDING
            item.player_id = player_id
            item.task_id = task.get('id')

            audit.record(session, current_user['user_id'], 'inventory.send',
                         target=player.in_game_username,
                         detail=f"{reward.kind} '{reward.name}' -> {player.in_game_username}@server{player.server_id}")

            return jsonify({'message': 'Delivery dispatched',
                            'item': item.to_dict(reward=reward)}), 200
    except Exception as e:
        logger.error(f"Send inventory item error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

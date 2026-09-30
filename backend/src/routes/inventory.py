"""Inventory routes: view won rewards and send/activate them for a character."""
import logging
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from src.database import db
from src.models.inventory_item import InventoryItem
from src.models.notification import Notification
from src.models.reward import Reward
from src.models.character import Character
from src.middleware.auth import token_required
from src.utils.game_server import gs_request
from src.utils.redis_utils import is_player_online
from src.utils import audit, expiry, notify, paging, alerting

logger = logging.getLogger(__name__)
inventory_bp = Blueprint('inventory', __name__, url_prefix='/api/inventory')


# An item whose delivery task cannot be resolved within this window is given
# back to the player rather than being stranded in 'sending' forever (the task
# row was cleared by an admin, the game-server is unreachable, or the task died).
SENDING_TIMEOUT = timedelta(minutes=5)


def _is_stale(item):
    """Whether a 'sending' item has been in flight past the recovery window."""
    started = item.sent_at or item.created_at
    return started is not None and datetime.utcnow() - started > SENDING_TIMEOUT


def _describe(session, item):
    """``(reward name, character name, server id)`` for an alert.

    Resolved here rather than in the webhook thread: by the time that runs this
    session is closed, and an alert saying "reward 41 to character 7" is not
    worth sending.
    """
    reward = session.get(Reward, item.reward_id)
    character = (session.query(Character).filter_by(id=item.character_id).first()
                 if item.character_id else None)
    return (reward.name if reward else f'reward {item.reward_id}',
            character.in_game_username if character else None,
            character.server_id if character else None)


def _release(session, item, reason=None):
    """Return an unresolvable in-flight item to the player's inventory.

    Tells the player: this used to fail silently, and they would only find out
    by reloading and noticing the item had come back.
    """
    item.status = InventoryItem.STATUS_HELD
    item.sent_at = None
    notify.send(session, item.user_id, Notification.KIND_DELIVERY,
                'A reward came back to your inventory',
                body=reason or 'It could not be delivered. You can try sending it again.',
                link='/rewards')

    name, character, server_id = _describe(session, item)
    alerting.emit('reward.failed', f'{name} came back undelivered',
                  description=reason, server_id=server_id,
                  fields=[('Reward', name), ('Character', character)])


def _reconcile(session, item):
    """Resolve a 'sending' item's status from its game-server delivery task.

    Anything that cannot be resolved is left alone until it goes stale, then
    handed back so the player can retry. Waiting for staleness rather than
    releasing immediately avoids refunding a delivery that is merely queued.
    """
    if item.status != InventoryItem.STATUS_SENDING:
        return
    if not item.task_id:
        # Dispatched but the task id was never recorded - nothing to poll.
        if _is_stale(item):
            _release(session, item, 'The delivery was never picked up.')
        return

    payload, status = gs_request('GET', f'/api/tasks/{item.task_id}')
    if status != 200:
        # 404 = the task row was cleared; anything else = game-server trouble.
        # Either way the outcome is now unknowable, so time it out.
        if _is_stale(item):
            _release(session, item, 'The server could not confirm the delivery.')
        return

    task = payload.get('data') or {}
    if task.get('status') != 'completed':
        # Still pending/processing, or stuck: the game-server fails abandoned
        # tasks on its own, but time out here too so a wedged queue can't hold
        # a player's item hostage.
        if _is_stale(item):
            _release(session, item, 'The delivery timed out.')
        return

    result = (task.get('data') or {}).get('result')
    if result == 'success':
        item.status = InventoryItem.STATUS_DELIVERED
        item.delivered_at = datetime.utcnow()
        notify.send(session, item.user_id, Notification.KIND_DELIVERY,
                    'Your reward was delivered',
                    body="It is in your character's inventory in game.",
                    link='/rewards')
        name, character, server_id = _describe(session, item)
        alerting.emit('reward.delivered', f'{name} was delivered to {character}',
                      server_id=server_id,
                      fields=[('Reward', name), ('Character', character)])
    else:
        # Failed (e.g. character went offline) -> return to inventory to retry.
        _release(session, item, 'The character went offline before it arrived.')


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
    """Send/activate an inventory item for one of the account's online characters."""
    data = request.get_json() or {}
    character_id = data.get('character_id')
    if not character_id:
        return jsonify({'error': 'character_id is required'}), 400

    try:
        with db.get_db() as session:
            item = (session.query(InventoryItem)
                    .filter_by(id=item_id, user_id=current_user['user_id'])
                    .first())
            if not item:
                return jsonify({'error': 'Inventory item not found'}), 404
            # Resolve any earlier in-flight delivery first, so a timed-out one
            # can be retried here without waiting for an inventory listing.
            _reconcile(session, item)
            if item.status == InventoryItem.STATUS_EXPIRED or expiry.is_expired(item):
                return jsonify({'error': 'That reward has expired'}), 409
            if item.status not in (InventoryItem.STATUS_HELD, InventoryItem.STATUS_FAILED):
                return jsonify({'error': 'Item is not available to send'}), 409

            character = (session.query(Character)
                         .filter_by(id=character_id, user_id=current_user['user_id'])
                         .first())
            if not character:
                return jsonify({'error': 'Character not found'}), 404
            if not character.is_deliverable():
                return jsonify({'error': 'That character is not linked/verified'}), 400
            if not is_player_online(character.server_id, character.in_game_username):
                return jsonify({'error': 'That character is not currently online'}), 409

            reward = session.get(Reward, item.reward_id)
            if not reward:
                return jsonify({'error': 'Reward no longer exists'}), 404

            payload = {
                'action': 'give_reward',
                'server_id': character.server_id,
                'username': character.in_game_username,
                'kind': reward.kind
            }
            if reward.kind == Reward.KIND_USABLE:
                # scope stays 'reward': the game-server refuses staff-only actions.
                if reward.commands:
                    payload['commands'] = reward.commands
                elif reward.action_id:   # legacy catalog reward, still deliverable
                    payload['action_id'] = reward.action_id
                    payload['action_params'] = reward.action_params or {}
                else:
                    return jsonify({'error': 'That reward is no longer deliverable'}), 409
            else:
                payload['in_game_id'] = reward.in_game_id
                # Quantity was captured onto the holding when the box was opened
                # (it lives on the box's pool entry, not the reward).
                payload['count'] = item.count or 1

            resp, status = gs_request('POST', '/api/tasks', json=payload)
            if status not in (200, 201):
                return jsonify({'error': resp.get('error', 'Failed to dispatch delivery')}), status

            task = resp.get('data') or {}
            item.status = InventoryItem.STATUS_SENDING
            item.character_id = character_id
            item.task_id = task.get('id')
            item.sent_at = datetime.utcnow()

            audit.record(session, current_user['user_id'], 'inventory.send',
                         target=character.in_game_username,
                         detail=f"{reward.kind} '{reward.name}' -> {character.in_game_username}@server{character.server_id}")

            return jsonify({'message': 'Delivery dispatched',
                            'item': item.to_dict(reward=reward)}), 200
    except Exception as e:
        logger.error(f"Send inventory item error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@inventory_bp.route('/remove', methods=['POST'])
@token_required
def remove_items(current_user):
    """Discard unsent rewards, or clear away used and expired ones.

    Anything in flight is left alone: its task on the manager may still land in
    game, and deleting the row would lose the record of it rather than stop it.
    """
    ids = (request.get_json(silent=True) or {}).get('ids')
    if not isinstance(ids, list) or not ids:
        return jsonify({'error': 'ids is required'}), 400
    try:
        ids = {int(i) for i in ids}
    except (TypeError, ValueError):
        return jsonify({'error': 'ids must be whole numbers'}), 400

    try:
        with db.get_db() as session:
            rows = (session.query(InventoryItem)
                    .filter(InventoryItem.user_id == current_user['user_id'],
                            InventoryItem.id.in_(ids),
                            InventoryItem.status != InventoryItem.STATUS_SENDING)
                    .with_for_update()
                    .all())
            discarded = sum(1 for r in rows if r.status in (InventoryItem.STATUS_HELD,
                                                            InventoryItem.STATUS_FAILED))
            for row in rows:
                session.delete(row)
            # Clearing used ones away is housekeeping; throwing away something
            # that could still be sent is worth a line in the audit trail.
            if discarded:
                audit.record(session, current_user['user_id'], 'inventory.discard',
                             detail=f'{discarded} unsent reward(s) discarded')
            return jsonify({'removed': len(rows)}), 200
    except Exception as e:
        logger.error(f"Remove inventory items error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@inventory_bp.route('/history', methods=['GET'])
@token_required
def inventory_history(current_user):
    """Rewards this account has already received, newest first.

    Everything needed was already recorded; only the view was missing.
    """
    try:
        limit, offset = paging.params(default_limit=50)
        with db.get_db() as session:
            query = (session.query(InventoryItem)
                     .filter_by(user_id=current_user['user_id'],
                                status=InventoryItem.STATUS_DELIVERED)
                     .order_by(InventoryItem.delivered_at.desc()))
            rows, total = paging.page(query, limit, offset)

            rewards = {r.id: r for r in session.query(Reward).all()}
            return jsonify({
                'history': [r.to_dict(reward=rewards.get(r.reward_id)) for r in rows],
                'pagination': paging.meta(total, limit, offset)
            }), 200
    except Exception as e:
        logger.error(f"Inventory history error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

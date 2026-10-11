"""Inventory routes: view won rewards and send/activate them for a character."""
import logging
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from src.database import db
from src.models.inventory_item import InventoryItem
from src.models.notification import Notification
from src.models.reward import Reward
from src.models.character import Character
from src.models.coin_log import CoinLog
from src.middleware.auth import token_required
from src.utils.game_server import gs_request
from src.utils.redis_utils import is_player_online
from src.utils import audit, coins, expiry, notify, paging, alerting

logger = logging.getLogger(__name__)
inventory_bp = Blueprint('inventory', __name__, url_prefix='/api/inventory')


# An item whose delivery task cannot be resolved within this window is given
# back to the player rather than being stranded in 'sending' forever (the task
# row was cleared by an admin, the game-server is unreachable, or the task died).
SENDING_TIMEOUT = timedelta(minutes=5)


# How many bundles one send may carry - the game-server's own cap
# (commands.BUNDLE_MAX / USABLE_BUNDLE_MAX), checked here as well so a player is
# told before anything is dispatched. A usable runs its whole sequence once per
# bundle, sleeps included, on the one queue every delivery waits behind.
SEND_MAX = {Reward.KIND_ITEM: 20, Reward.KIND_USABLE: 5}


def _is_stale(item):
    """Whether a 'sending' item has been in flight past the recovery window."""
    started = item.sent_at or item.created_at
    return started is not None and datetime.utcnow() - started > SENDING_TIMEOUT


def _what(reward, items):
    """How a delivery reads to a person: "Bandage", "Bandage ×5", "3 × Bandage ×5".

    The number after the name is what one bundle holds; the one before it is
    how many bundles. Kept apart because they mean different things - three
    drops of five bandages are not one drop of fifteen.
    """
    name = reward.name if reward else f'reward {items[0].reward_id}'
    per = items[0].count or 1
    if per > 1 and not (reward and reward.kind == Reward.KIND_USABLE):
        name = f'{name} ×{per}'
    return f'{len(items)} × {name}' if len(items) > 1 else name


def _describe(session, items):
    """``(what, character name, server id)`` for an alert.

    Resolved here rather than in the webhook thread: by the time that runs this
    session is closed, and an alert saying "reward 41 to character 7" is not
    worth sending.
    """
    first = items[0]
    reward = session.get(Reward, first.reward_id)
    character = (session.query(Character).filter_by(id=first.character_id).first()
                 if first.character_id else None)
    return (_what(reward, items),
            character.in_game_username if character else None,
            character.server_id if character else None)


def _release(session, items, reason=None):
    """Return unresolvable in-flight bundles to the player's inventory.

    One message for the whole delivery, not one per bundle: the player sent it
    as one thing. This used to fail silently, and they would only find out by
    reloading and noticing the item had come back.
    """
    for item in items:
        item.status = InventoryItem.STATUS_HELD
        item.sent_at = None
    what, character, server_id = _describe(session, items)
    notify.send(session, items[0].user_id, Notification.KIND_DELIVERY,
                f'{what} came back to your inventory',
                body=reason or 'It could not be delivered. You can try sending it again.',
                link='/rewards')
    alerting.emit('reward.failed', f'{what} came back undelivered',
                  description=reason, server_id=server_id,
                  fields=[('Reward', what), ('Character', character)])


def _deliver(session, items):
    """Mark in-flight bundles as having arrived in game."""
    now = datetime.utcnow()
    for item in items:
        item.status = InventoryItem.STATUS_DELIVERED
        item.delivered_at = now
    what, character, server_id = _describe(session, items)
    notify.send(session, items[0].user_id, Notification.KIND_DELIVERY,
                f'{what} was delivered',
                body="It is in your character's inventory in game.",
                link='/rewards')
    alerting.emit('reward.delivered', f'{what} was delivered to {character}',
                  server_id=server_id,
                  fields=[('Reward', what), ('Character', character)])


def _reconcile(session, items):
    """Resolve one delivery's in-flight bundles from its game-server task.

    ``items`` are the rows a single task carries (see :func:`_deliveries`).
    Anything that cannot be resolved is left alone until it goes stale, then
    handed back so the player can retry. Waiting for staleness rather than
    releasing immediately avoids refunding a delivery that is merely queued.

    A task that failed part-way reports the bundles that did land
    (``delivered_refs``); those are delivered and only the rest come back, so a
    half-finished send can never be sent again in full. A task without the field
    predates stack deliveries and carried one bundle, which did not arrive.
    """
    items = [i for i in items if i.status == InventoryItem.STATUS_SENDING]
    if not items:
        return
    task_id = items[0].task_id
    if not task_id:
        # Dispatched but the task id was never recorded - nothing to poll.
        if _is_stale(items[0]):
            _release(session, items, 'The delivery was never picked up.')
        return

    payload, status = gs_request('GET', f'/api/tasks/{task_id}')
    if status != 200:
        # 404 = the task row was cleared; anything else = game-server trouble.
        # Either way the outcome is now unknowable, so time it out.
        if _is_stale(items[0]):
            _release(session, items, 'The server could not confirm the delivery.')
        return

    task = payload.get('data') or {}
    if task.get('status') != 'completed':
        # Still pending/processing, or stuck: the game-server fails abandoned
        # tasks on its own, but time out here too so a wedged queue can't hold
        # a player's item hostage.
        if _is_stale(items[0]):
            _release(session, items, 'The delivery timed out.')
        return

    data = task.get('data') or {}
    if data.get('result') == 'success':
        _deliver(session, items)
        return
    landed = set(data.get('delivered_refs') or [])
    arrived = [i for i in items if i.id in landed]
    back = [i for i in items if i.id not in landed]
    if arrived:
        _deliver(session, arrived)
    if back:
        # Failed (e.g. character went offline) -> return to inventory to retry.
        _release(session, back,
                 'Only part of it arrived before the delivery stopped.' if arrived
                 else 'The character went offline before it arrived.')


def _deliveries(items):
    """Group in-flight rows by the task carrying them.

    A stack send is one task for several rows, and resolving it row by row would
    tell the player the same news once per bundle. A row with no task id is its
    own delivery.
    """
    groups = {}
    for item in items:
        if item.status != InventoryItem.STATUS_SENDING:
            continue
        key = ('task', item.task_id) if item.task_id else ('row', item.id)
        groups.setdefault(key, []).append(item)
    return list(groups.values())


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
            for delivery in _deliveries(items):
                _reconcile(session, delivery)

            reward_ids = {i.reward_id for i in items}
            rewards = ({r.id: r for r in session.query(Reward).filter(Reward.id.in_(reward_ids))}
                       if reward_ids else {})
            return jsonify({
                'inventory': [i.to_dict(reward=rewards.get(i.reward_id)) for i in items],
                'send_max': SEND_MAX,
            }), 200
    except Exception as e:
        logger.error(f"List inventory error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


def _send(user_id, ids, character_id):
    """Send bundles of one reward to one character, as a single delivery.

    The bundles must be the same reward holding the same amount - one stack as
    the player sees it - and all still here to send. Everything is checked
    before anything is dispatched, and one task carries them all, so a send
    either goes out whole or not at all; there is no half-sent stack to explain.
    Returns ``(body, status)``.
    """
    if not character_id:
        return {'error': 'character_id is required'}, 400
    with db.get_db() as session:
        # Locked so two sends of the same bundle cannot both dispatch it.
        items = (session.query(InventoryItem)
                 .filter(InventoryItem.user_id == user_id, InventoryItem.id.in_(ids))
                 .order_by(InventoryItem.id)
                 .with_for_update()
                 .all())
        if len(items) != len(ids):
            return {'error': 'Some of those rewards are no longer in your inventory'}, 404

        # Resolve any earlier in-flight delivery first, so a timed-out one can
        # be retried here without waiting for an inventory listing - the whole
        # delivery, not only the rows asked for, so it is reported once.
        task_ids = {i.task_id for i in items
                    if i.status == InventoryItem.STATUS_SENDING and i.task_id}
        in_flight = [i for i in items if i.status == InventoryItem.STATUS_SENDING and not i.task_id]
        if task_ids:
            in_flight += (session.query(InventoryItem)
                          .filter(InventoryItem.user_id == user_id,
                                  InventoryItem.task_id.in_(task_ids))
                          .with_for_update()
                          .all())
        for delivery in _deliveries(in_flight):
            _reconcile(session, delivery)

        first = items[0]
        if any(i.reward_id != first.reward_id or (i.count or 1) != (first.count or 1)
               for i in items):
            return {'error': 'Only bundles of the same reward can be sent together'}, 400
        if any(i.status == InventoryItem.STATUS_EXPIRED or expiry.is_expired(i) for i in items):
            return {'error': 'That reward has expired'}, 409
        if any(i.status not in InventoryItem.SELLABLE for i in items):
            return {'error': 'That reward is not available to send'}, 409

        reward = session.get(Reward, first.reward_id)
        if not reward:
            return {'error': 'Reward no longer exists'}, 404
        limit = SEND_MAX.get(reward.kind, SEND_MAX[Reward.KIND_ITEM])
        if len(items) > limit:
            return {'error': f'You can send up to {limit} at a time'}, 400

        character = (session.query(Character)
                     .filter_by(id=character_id, user_id=user_id)
                     .first())
        if not character:
            return {'error': 'Character not found'}, 404
        if not character.is_deliverable():
            return {'error': 'That character is not linked/verified'}, 400
        if not is_player_online(character.server_id, character.in_game_username):
            return {'error': 'That character is not currently online'}, 409

        payload = {
            'action': 'give_reward',
            'server_id': character.server_id,
            'username': character.in_game_username,
            'kind': reward.kind,
            # Each bundle by its row id, which the task echoes back for the ones
            # that landed. The amount was captured onto the row when it was won
            # (it lives on the box's pool entry or the listing, not the reward).
            'bundles': [{'ref': i.id, 'count': i.count or 1} for i in items],
        }
        if reward.kind == Reward.KIND_USABLE:
            # scope stays 'reward': the game-server refuses staff-only actions.
            if reward.commands:
                payload['commands'] = reward.commands
            elif reward.action_id:   # legacy catalog reward, still deliverable
                payload['action_id'] = reward.action_id
                payload['action_params'] = reward.action_params or {}
            else:
                return {'error': 'That reward is no longer deliverable'}, 409
        else:
            payload['in_game_id'] = reward.in_game_id

        resp, status = gs_request('POST', '/api/tasks', json=payload)
        if status not in (200, 201):
            return {'error': resp.get('error', 'Failed to dispatch delivery')}, status

        task = resp.get('data') or {}
        now = datetime.utcnow()
        for item in items:
            item.status = InventoryItem.STATUS_SENDING
            item.character_id = character.id
            item.task_id = task.get('id')
            item.sent_at = now

        audit.record(session, user_id, 'inventory.send',
                     target=character.in_game_username,
                     detail=f"{reward.kind} {_what(reward, items)} -> "
                            f"{character.in_game_username}@server{character.server_id}")

        return {'message': 'Delivery dispatched',
                'items': [i.to_dict(reward=reward) for i in items]}, 200


def _ids(raw):
    """A request's list of inventory ids, or an error message."""
    if not isinstance(raw, list) or not raw:
        return None, 'ids is required'
    if any(isinstance(i, bool) or not isinstance(i, int) for i in raw):
        return None, 'ids must be whole numbers'
    if len(set(raw)) != len(raw):
        return None, 'ids must not repeat'
    return raw, None


@inventory_bp.route('/send', methods=['POST'])
@token_required
def send_items(current_user):
    """Send bundles of one reward to one of the account's online characters."""
    data = request.get_json(silent=True) or {}
    ids, error = _ids(data.get('ids'))
    if error:
        return jsonify({'error': error}), 400
    most = max(SEND_MAX.values())
    if len(ids) > most:
        return jsonify({'error': f'You can send up to {most} at a time'}), 400
    try:
        body, status = _send(current_user['user_id'], ids, data.get('character_id'))
        return jsonify(body), status
    except Exception as e:
        logger.error(f"Send inventory items error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@inventory_bp.route('/<int:item_id>/send', methods=['POST'])
@token_required
def send_item(current_user, item_id):
    """Send one bundle. A bundle goes whole: there is no sending part of one."""
    data = request.get_json(silent=True) or {}
    if data.get('count') is not None:
        # A client from before bundles asking for part of one. Refused rather
        # than ignored, so nobody gets more than they asked for.
        return jsonify({'error': 'A reward is sent whole - refresh the page and try again'}), 400
    try:
        body, status = _send(current_user['user_id'], [item_id], data.get('character_id'))
        if status == 200:
            body['item'] = body.pop('items')[0]
        return jsonify(body), status
    except Exception as e:
        logger.error(f"Send inventory item error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@inventory_bp.route('/remove', methods=['POST'])
@token_required
def remove_items(current_user):
    """Discard unsent rewards, or clear away used and expired ones.

    With coins switched on, discarding is selling: each unsent holding pays its
    reward's coin value once, in the same transaction that deletes it, so a
    reward is either still here or paid for - never both, never neither. The
    rows are locked, so two discards of the same holding cannot both pay.

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
    selling = coins.enabled()

    try:
        with db.get_db() as session:
            user_id = current_user['user_id']
            rows = (session.query(InventoryItem)
                    .filter(InventoryItem.user_id == user_id,
                            InventoryItem.id.in_(ids),
                            InventoryItem.status != InventoryItem.STATUS_SENDING)
                    .with_for_update()
                    .all())
            discarded = sum(1 for r in rows if r.status in InventoryItem.SELLABLE)

            earned = sold = 0
            names = []
            if selling and discarded:
                reward_ids = {r.reward_id for r in rows}
                rewards = {r.id: r for r in
                           session.query(Reward).filter(Reward.id.in_(reward_ids))}
                now = datetime.utcnow()
                for row in rows:
                    value = row.sell_value(rewards.get(row.reward_id), now)
                    if value:
                        earned += value
                        sold += 1
                        names.append(rewards[row.reward_id].name)

            for row in rows:
                session.delete(row)
            if earned:
                coins.earn(session, user_id, earned, CoinLog.SOURCE_SALE, quantity=sold,
                           detail=', '.join(sorted(set(names))))
            # Clearing used ones away is housekeeping; throwing away something
            # that could still be sent is worth a line in the audit trail.
            if discarded:
                audit.record(session, user_id, 'inventory.discard',
                             detail=f'{discarded} unsent reward(s) discarded'
                                    + (f', sold for {earned} coin(s)' if earned else ''))

            body = {'removed': len(rows), 'coins': earned}
            if selling:
                body['balance'] = coins.balance(session, user_id)
            return jsonify(body), 200
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

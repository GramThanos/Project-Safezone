"""Loot box routes: claiming due boxes, and opening them."""
import logging
from datetime import datetime, timedelta
from flask import Blueprint, jsonify
from sqlalchemy.exc import IntegrityError
from src.database import db
from src.models.box import Box
from src.models.event import Event
from src.models.user_box import UserBox
from src.models.box_loot_pool import BoxLootPool
from src.models.reward import Reward
from src.models.inventory_item import InventoryItem
from src.middleware.auth import token_required
from src.utils import daily, loot, events, expiry

logger = logging.getLogger(__name__)
boxes_bp = Blueprint('boxes', __name__, url_prefix='/api/boxes')


def _period_key(event, today):
    """The grant period this event uses, so a repeat claim is a no-op.

    A one-time custom event is keyed to the constant ``'once'`` so it can only
    ever be granted a single time; everything else is keyed to the day.
    """
    if event.type == Event.TYPE_CUSTOM and event.cadence == Event.CADENCE_ONCE:
        return UserBox.ONCE
    return today.isoformat()


@boxes_bp.route('/daily', methods=['POST'])
@token_required
def claim_daily(current_user):
    """Grant every box the account is currently due but has not yet received.

    That is the daily event's box plus one from each active custom event. Each
    grant is guarded by the unique ``(user_id, event_id, period_key)`` key, so a
    second claim in the same period simply grants nothing new.
    """
    user_id = current_user['user_id']
    # The day boundary follows the primary game server's timezone, so boxes
    # reset when players experience a new day (not at UTC midnight).
    today = daily.today()
    now = datetime.utcnow()
    granted = []
    try:
        with db.get_db() as session:
            for event in events.grant_events(session, now):
                box_id = events.pick_box_for_event(session, event.id)
                if box_id is None:
                    # Enabled but with nothing droppable attached: skip it rather
                    # than grant a box that cannot be opened.
                    continue

                period_key = _period_key(event, today)
                # The common case (a repeat claim in the same period) is settled
                # with a read, so no exception is raised and no work is undone.
                already = (session.query(UserBox.id)
                           .filter_by(user_id=user_id, event_id=event.id,
                                      period_key=period_key)
                           .first())
                if already:
                    continue

                box = UserBox(user_id=user_id, box_id=box_id, event_id=event.id,
                              source=event.source, period_key=period_key,
                              grant_date=today, expires_at=expiry.box_deadline())
                try:
                    # A savepoint, so a lost race on the unique key rolls back only
                    # this insert and not the boxes already granted this claim.
                    #
                    # The `add` belongs *inside* the savepoint. Adding first and
                    # only flushing inside leaves the pending insert outside the
                    # SAVEPOINT's snapshot, so rolling back does not undo it: the
                    # session stays in a failed state and the commit this block's
                    # caller makes raises PendingRollbackError - turning a lost
                    # race into a 500 that discards every box granted above it.
                    with session.begin_nested():
                        session.add(box)
                        session.flush()
                except IntegrityError:
                    continue

                box_row = session.get(Box, box_id)
                granted.append(box.to_dict(box=box_row))

            return jsonify({
                'granted': bool(granted),
                'boxes': granted,
                # The first new box, for the welcome panel that shows one crate.
                'box': granted[0] if granted else None,
            }), 201 if granted else 200
    except Exception as e:
        logger.error(f"Claim daily box error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@boxes_bp.route('', methods=['GET'])
@token_required
def list_boxes(current_user):
    """List the account's unopened loot boxes."""
    try:
        with db.get_db() as session:
            rows = (session.query(UserBox)
                    .filter_by(user_id=current_user['user_id'], status=UserBox.STATUS_UNOPENED)
                    .order_by(UserBox.granted_at.desc())
                    .all())
            boxes_by_id = {b.id: b for b in session.query(Box).all()}
            # Hide anything already past its deadline even if the sweep has not
            # run yet, so the UI never offers a box that will refuse to open.
            out = [row.to_dict(box=boxes_by_id.get(row.box_id))
                   for row in rows if not expiry.is_expired(row)]
            return jsonify({'boxes': out}), 200
    except Exception as e:
        logger.error(f"List boxes error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@boxes_bp.route('/<int:box_id>/open', methods=['POST'])
@token_required
def open_box(current_user, box_id):
    """Open a box: draw rewards from its pool into the account inventory."""
    try:
        with db.get_db() as session:
            # Lock the row for the transaction: without it two concurrent opens
            # both read 'unopened' and both draw, duplicating the loot.
            user_box = (session.query(UserBox)
                        .filter_by(id=box_id, user_id=current_user['user_id'])
                        .with_for_update()
                        .first())
            if not user_box:
                return jsonify({'error': 'Box not found'}), 404
            if user_box.status == UserBox.STATUS_OPENED:
                return jsonify({'error': 'Box already opened'}), 409
            if user_box.status == UserBox.STATUS_REVOKED:
                return jsonify({'error': 'That box was removed by staff'}), 409
            if user_box.status == UserBox.STATUS_EXPIRED or expiry.is_expired(user_box):
                return jsonify({'error': 'That box has expired'}), 409

            box = session.get(Box, user_box.box_id)
            if not box:
                logger.warning(f"UserBox {user_box.id} references missing box {user_box.box_id}")
                return jsonify({'error': 'This box no longer exists'}), 409

            # Eligible rewards: in this box's pool and currently active. The
            # weight and count are per pool entry, so the same reward can be
            # common in one box and rare in another, and drop in different
            # quantities.
            entries = (session.query(BoxLootPool)
                       .join(Reward, Reward.id == BoxLootPool.reward_id)
                       .filter(BoxLootPool.box_id == box.id, Reward.active.is_(True))
                       .all())
            pool = [(p.reward_id, p.weight) for p in entries]
            count_by_reward = {p.reward_id: (p.count or 1) for p in entries}
            drawn = loot.draw_weighted(pool, box.draws)
            if not drawn:
                # Nothing to give: keep the box rather than consuming it for
                # nothing. An empty pool is a misconfiguration, not a bad roll.
                logger.warning(
                    f"Box {user_box.id} ('{box.name}') not opened: no active rewards in "
                    f"its loot pool"
                )
                return jsonify({
                    'error': "This box can't be opened yet - its loot pool is empty. "
                             "Please let an admin know."
                }), 409

            items = []
            for reward_id in drawn:
                inv = InventoryItem(
                    user_id=current_user['user_id'],
                    reward_id=reward_id,
                    count=count_by_reward.get(reward_id, 1),
                    source=InventoryItem.SOURCE_BOX,
                    source_box_id=user_box.id,
                    status=InventoryItem.STATUS_HELD,
                    expires_at=expiry.inventory_deadline()
                )
                session.add(inv)
                items.append(inv)

            user_box.status = UserBox.STATUS_OPENED
            user_box.opened_at = datetime.utcnow()
            session.flush()

            result = []
            for inv in items:
                reward = session.get(Reward, inv.reward_id)
                result.append(inv.to_dict(reward=reward))
            return jsonify({'message': 'Box opened', 'items': result}), 200
    except Exception as e:
        logger.error(f"Open box error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@boxes_bp.route('/streak', methods=['GET'])
@token_required
def streak(current_user):
    """This week's collected days, and what they are worth.

    The week matches the job that pays the bonus: Monday to Sunday in the
    primary server's timezone, the same boundary as the daily reset. "Collected"
    counts distinct days on which the daily event granted a box.
    """
    try:
        from src.utils import settings
        threshold = settings.get('streak_threshold') or 5

        today = daily.today()
        week_start = today - timedelta(days=today.isoweekday() - 1)   # this Monday
        week_end = week_start + timedelta(days=6)                     # its Sunday

        with db.get_db() as session:
            enabled = events.weekly_bonus_enabled(session)
            days = [row[0] for row in
                    (session.query(UserBox.grant_date)
                     .filter(UserBox.user_id == current_user['user_id'],
                             UserBox.source == UserBox.SOURCE_DAILY,
                             UserBox.grant_date >= week_start,
                             UserBox.grant_date <= week_end)
                     .distinct()
                     .all())]

        collected = len(days)
        return jsonify({
            'enabled': bool(enabled),
            'collected': collected,
            'threshold': threshold,
            'week_start': week_start.isoformat(),
            'week_end': week_end.isoformat(),
            # Which weekdays are already in, so the UI can draw the week rather
            # than just count it. 1 = Monday.
            'days': sorted(d.isoweekday() for d in days),
            'today': today.isoweekday(),
            'earned': collected >= threshold,
            'remaining': max(0, threshold - collected),
            # Days left that could still be collected, so the UI can say when a
            # streak has become impossible instead of implying it is still live.
            'days_left': max(0, 7 - today.isoweekday()),
        }), 200
    except Exception as e:
        logger.error(f"Streak error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@boxes_bp.route('/odds', methods=['GET'])
def box_odds():
    """What each event's boxes can contain, and how likely each reward is.

    Public and unauthenticated. Published odds are a legal requirement for loot
    boxes in several jurisdictions, and the data to publish them already exists -
    withholding it was never a feature. Grouped by the events a player can
    currently receive from, then by the boxes each event can grant.
    """
    try:
        now = datetime.utcnow()
        with db.get_db() as session:
            rewards_by_id = {r.id: r for r in session.query(Reward).all()}
            pool_entries = session.query(BoxLootPool).all()
            boxes_by_id = {b.id: b for b in session.query(Box).all()}

            def box_contents(box):
                mine = [e for e in pool_entries
                        if e.box_id == box.id
                        and rewards_by_id.get(e.reward_id) is not None
                        and rewards_by_id[e.reward_id].active]
                pool = [(e.reward_id, e.weight) for e in mine]
                # Quantity lives on the pool entry, so the same item can be
                # published at a different count in a different box. Part of the
                # disclosure: "a 5% chance of bandages" means something different
                # when it is five bandages.
                counts = {e.reward_id: (e.count or 1) for e in mine}
                contents = []
                for reward_id, probability in loot.odds(pool):
                    reward = rewards_by_id[reward_id]
                    contents.append({
                        'reward': {
                            'id': reward.id,
                            'name': reward.name,
                            'description': reward.description,
                            'icon': reward.icon,
                            'kind': reward.kind,
                        },
                        # How many drop when this entry is the one picked. Always
                        # 1 for a usable - a command sequence runs once.
                        'count': counts.get(reward_id, 1)
                        if reward.kind == Reward.KIND_ITEM else 1,
                        # Chance for a single draw. A box makes `draws` of them.
                        'chance': round(probability, 6),
                    })
                contents.sort(key=lambda c: c['chance'], reverse=True)
                return contents

            # The events a player can currently receive from: the enabled daily
            # and weekly-bonus events, plus every live custom event.
            shown = []
            daily_event = events.system_event(session, Event.TYPE_DAILY)
            weekly = events.system_event(session, Event.TYPE_WEEKLY_BONUS)
            for event in (daily_event, weekly):
                if event and event.enabled:
                    shown.append(event)
            for event in (session.query(Event)
                          .filter(Event.type == Event.TYPE_CUSTOM, Event.enabled.is_(True))
                          .order_by(Event.id).all()):
                if event.is_live(now):
                    shown.append(event)

            result = []
            for event in shown:
                entries = events.event_box_entries(session, event.id)
                total = sum(weight for _, weight in entries)
                box_list = []
                for box_id, weight in entries:
                    box = boxes_by_id.get(box_id)
                    if not box:
                        continue
                    box_list.append({
                        'id': box.id,
                        'name': box.name,
                        'draws': box.draws,
                        # Chance this box is the one granted when the event fires.
                        'pick_chance': (weight / total) if total > 0 else 0.0,
                        'contents': box_contents(box),
                    })
                result.append({
                    'event': {'id': event.id, 'type': event.type, 'name': event.name},
                    'boxes': box_list,
                })

            return jsonify({'events': result}), 200
    except Exception as e:
        logger.error(f"Box odds error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

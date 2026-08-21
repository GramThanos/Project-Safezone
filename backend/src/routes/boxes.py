"""Loot box routes: daily grant and opening."""
import logging
from datetime import datetime, timedelta
from flask import Blueprint, jsonify
from sqlalchemy.exc import IntegrityError
from src.database import db
from src.models.user_box import UserBox
from src.models.box_loot_pool import BoxLootPool
from src.models.reward import Reward
from src.models.inventory_item import InventoryItem
from src.middleware.auth import token_required
from src.utils import daily, loot, box_types, expiry, settings

logger = logging.getLogger(__name__)
boxes_bp = Blueprint('boxes', __name__, url_prefix='/api/boxes')


@boxes_bp.route('/daily', methods=['POST'])
@token_required
def claim_daily(current_user):
    """Grant today's loot box if the account hasn't received one yet today."""
    user_id = current_user['user_id']
    # The day boundary follows the primary game server's timezone, so the box
    # resets when players experience a new day (not at UTC midnight).
    today = daily.today()
    try:
        with db.get_db() as session:
            types = box_types.all_types()
            box = UserBox(user_id=user_id, size=loot.pick_box_size(types=types),
                          grant_date=today, source=UserBox.SOURCE_DAILY,
                          expires_at=expiry.box_deadline())
            session.add(box)
            try:
                session.flush()
            except IntegrityError:
                # Unique (user_id, grant_date) violated -> already granted today.
                session.rollback()
                existing = (session.query(UserBox)
                            .filter_by(user_id=user_id, grant_date=today,
                                       source=UserBox.SOURCE_DAILY)
                            .first())
                return jsonify({'granted': False,
                                'box': existing.to_dict() if existing else None}), 200
            return jsonify({'granted': True, 'box': box.to_dict()}), 201
    except Exception as e:
        logger.error(f"Claim daily box error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@boxes_bp.route('', methods=['GET'])
@token_required
def list_boxes(current_user):
    """List the account's unopened loot boxes."""
    try:
        with db.get_db() as session:
            boxes = (session.query(UserBox)
                     .filter_by(user_id=current_user['user_id'], status=UserBox.STATUS_UNOPENED)
                     .order_by(UserBox.granted_at.desc())
                     .all())
            # Hide anything already past its deadline even if the sweep has not
            # run yet, so the UI never offers a box that will refuse to open.
            boxes = [b for b in boxes if not expiry.is_expired(b)]
            return jsonify({'boxes': [b.to_dict() for b in boxes]}), 200
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
            box = (session.query(UserBox)
                   .filter_by(id=box_id, user_id=current_user['user_id'])
                   .with_for_update()
                   .first())
            if not box:
                return jsonify({'error': 'Box not found'}), 404
            if box.status == UserBox.STATUS_OPENED:
                return jsonify({'error': 'Box already opened'}), 409
            if box.status == UserBox.STATUS_EXPIRED or expiry.is_expired(box):
                return jsonify({'error': 'That box has expired'}), 409

            # Eligible rewards: in this size's pool and currently active. The
            # weight is per pool entry, so the same reward can be common in one
            # size and rare in another.
            pool = [(p.reward_id, p.weight) for p in (
                session.query(BoxLootPool)
                .join(Reward, Reward.id == BoxLootPool.reward_id)
                .filter(BoxLootPool.size == box.size, Reward.active.is_(True))
                .all()
            )]
            drawn = loot.draw_weighted(pool, loot.draw_count(box.size, box_types.all_types()))
            if not drawn:
                # Nothing to give: keep the box rather than consuming it for
                # nothing. An empty pool is a misconfiguration, not a bad roll.
                logger.warning(
                    f"Box {box.id} ({box.size}) not opened: no active rewards in the "
                    f"'{box.size}' loot pool"
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
                    source=InventoryItem.SOURCE_BOX,
                    source_box_id=box.id,
                    status=InventoryItem.STATUS_HELD,
                    expires_at=expiry.inventory_deadline()
                )
                session.add(inv)
                items.append(inv)

            box.status = UserBox.STATUS_OPENED
            box.opened_at = datetime.utcnow()
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

    The weekly bonus has always been paid; it was just never shown. A player
    could not see that a streak existed, how far into one they were, or what
    finishing it gave them - which makes it a retention mechanic nobody could
    aim at.

    The week matches the job that pays the bonus: Monday to Sunday in the
    primary server's timezone, the same boundary as the daily reset.
    """
    try:
        enabled = settings.get('streak_bonus_enabled')
        threshold = settings.get('streak_threshold') or 5

        today = daily.today()
        week_start = today - timedelta(days=today.isoweekday() - 1)   # this Monday
        week_end = week_start + timedelta(days=6)                     # its Sunday

        with db.get_db() as session:
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
    """What each box size can contain, and how likely each reward is.

    Public and unauthenticated. Published odds are a legal requirement for loot
    boxes in several jurisdictions, and the data to publish them already exists -
    withholding it was never a feature.
    """
    try:
        with db.get_db() as session:
            rewards_by_id = {r.id: r for r in session.query(Reward).all()}
            entries = session.query(BoxLootPool).all()

            types = box_types.all_types()
            total_weight = sum(
                spec.get('weight', 0) for spec in types.values()
                if spec.get('active', True) and spec.get('weight', 0) > 0
            )

            result = []
            for size, spec in types.items():
                pool = [
                    (e.reward_id, e.weight) for e in entries
                    if e.size == size
                    and rewards_by_id.get(e.reward_id) is not None
                    and rewards_by_id[e.reward_id].active
                ]
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
                        # Chance for a single draw. A box makes `draws` of them.
                        'chance': round(probability, 6),
                    })
                contents.sort(key=lambda c: c['chance'], reverse=True)

                result.append({
                    'size': size,
                    'label': spec.get('label', size.title()),
                    'draws': spec.get('draws', 0),
                    'daily_chance': (spec.get('weight', 0) / total_weight
                                     if total_weight > 0 and spec.get('active', True)
                                     and spec.get('weight', 0) > 0 else 0.0),
                    'contents': contents,
                })

            return jsonify({'boxes': result}), 200
    except Exception as e:
        logger.error(f"Box odds error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

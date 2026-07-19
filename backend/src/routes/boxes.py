"""Loot box routes: daily grant and opening."""
import logging
from datetime import datetime
from flask import Blueprint, jsonify
from sqlalchemy.exc import IntegrityError
from src.database import db
from src.models.user_box import UserBox
from src.models.box_loot_pool import BoxLootPool
from src.models.reward import Reward
from src.models.inventory_item import InventoryItem
from src.middleware.auth import token_required
from src.utils import loot

logger = logging.getLogger(__name__)
boxes_bp = Blueprint('boxes', __name__, url_prefix='/api/boxes')


@boxes_bp.route('/daily', methods=['POST'])
@token_required
def claim_daily(current_user):
    """Grant today's loot box if the account hasn't received one yet today."""
    user_id = current_user['user_id']
    today = datetime.utcnow().date()
    try:
        with db.get_db() as session:
            box = UserBox(user_id=user_id, size=loot.pick_box_size(), grant_date=today)
            session.add(box)
            try:
                session.flush()
            except IntegrityError:
                # Unique (user_id, grant_date) violated -> already granted today.
                session.rollback()
                existing = (session.query(UserBox)
                            .filter_by(user_id=user_id, grant_date=today)
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
            box = (session.query(UserBox)
                   .filter_by(id=box_id, user_id=current_user['user_id'])
                   .first())
            if not box:
                return jsonify({'error': 'Box not found'}), 404
            if box.status == UserBox.STATUS_OPENED:
                return jsonify({'error': 'Box already opened'}), 409

            # Eligible rewards: in this size's pool and currently active.
            pool_ids = [p.reward_id for p in (
                session.query(BoxLootPool)
                .join(Reward, Reward.id == BoxLootPool.reward_id)
                .filter(BoxLootPool.size == box.size, Reward.active.is_(True))
                .all()
            )]
            drawn = loot.draw_rewards(pool_ids, loot.draw_count(box.size))

            items = []
            for reward_id in drawn:
                inv = InventoryItem(
                    user_id=current_user['user_id'],
                    reward_id=reward_id,
                    source=InventoryItem.SOURCE_BOX,
                    source_box_id=box.id,
                    status=InventoryItem.STATUS_HELD
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

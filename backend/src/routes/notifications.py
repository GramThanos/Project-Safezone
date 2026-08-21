"""The signed-in account's inbox."""
import logging
from datetime import datetime

from flask import Blueprint, request, jsonify

from src.database import db
from src.models.notification import Notification
from src.middleware.auth import token_required
from src.utils import paging

logger = logging.getLogger(__name__)
notifications_bp = Blueprint('notifications', __name__, url_prefix='/api/notifications')


@notifications_bp.route('', methods=['GET'])
@token_required
def list_notifications(current_user):
    """Unread first, then newest. `?unread=1` narrows to unread only."""
    try:
        limit, offset = paging.params(default_limit=25)
        with db.get_db() as session:
            query = session.query(Notification).filter_by(user_id=current_user['user_id'])
            if request.args.get('unread') in ('1', 'true'):
                query = query.filter(Notification.read_at.is_(None))

            unread = (session.query(Notification)
                      .filter_by(user_id=current_user['user_id'])
                      .filter(Notification.read_at.is_(None))
                      .count())

            query = query.order_by(Notification.read_at.is_(None).desc(),
                                   Notification.created_at.desc())
            rows, total = paging.page(query, limit, offset)

            return jsonify({
                'notifications': [r.to_dict() for r in rows],
                'unread': unread,
                'pagination': paging.meta(total, limit, offset)
            }), 200
    except Exception as e:
        logger.error(f"List notifications error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@notifications_bp.route('/unread-count', methods=['GET'])
@token_required
def unread_count(current_user):
    """Just the badge number - polled often, so it stays cheap."""
    try:
        with db.get_db() as session:
            count = (session.query(Notification)
                     .filter_by(user_id=current_user['user_id'])
                     .filter(Notification.read_at.is_(None))
                     .count())
            return jsonify({'unread': count}), 200
    except Exception as e:
        logger.error(f"Unread count error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@notifications_bp.route('/<int:notification_id>/read', methods=['POST'])
@token_required
def mark_read(current_user, notification_id):
    """Mark one as read. Idempotent."""
    try:
        with db.get_db() as session:
            row = (session.query(Notification)
                   .filter_by(id=notification_id, user_id=current_user['user_id'])
                   .first())
            if not row:
                return jsonify({'error': 'Notification not found'}), 404
            if row.read_at is None:
                row.read_at = datetime.utcnow()
            return jsonify({'message': 'Marked as read'}), 200
    except Exception as e:
        logger.error(f"Mark read error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@notifications_bp.route('/<int:notification_id>', methods=['DELETE'])
@token_required
def delete_notification(current_user, notification_id):
    """Remove one notification.

    Reading and removing are different acts: "I have seen this" is not "I no
    longer want this in my list". Without a delete the list only ever grew, and
    after a few months of daily deliveries the one message that mattered was
    buried in an archive of ones that did not.

    Scoped to the caller's own rows, so an id from someone else's account is a
    404 rather than a deletion.
    """
    try:
        with db.get_db() as session:
            row = (session.query(Notification)
                   .filter_by(id=notification_id, user_id=current_user['user_id'])
                   .first())
            if not row:
                return jsonify({'error': 'Notification not found'}), 404
            session.delete(row)
            return jsonify({'message': 'Notification removed'}), 200
    except Exception as e:
        logger.error(f"Delete notification error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@notifications_bp.route('/read', methods=['DELETE'])
@token_required
def clear_read(current_user):
    """Remove every notification the caller has already read.

    The bulk version of the above, and deliberately limited to read ones: an
    unread notification is news the player has not seen, and a "clear" that
    silently threw it away would lose exactly the message worth keeping.
    """
    try:
        with db.get_db() as session:
            removed = (session.query(Notification)
                       .filter_by(user_id=current_user['user_id'])
                       .filter(Notification.read_at.isnot(None))
                       .delete(synchronize_session=False))
            return jsonify({'message': f'Removed {removed}', 'count': removed}), 200
    except Exception as e:
        logger.error(f"Clear read notifications error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@notifications_bp.route('/read-all', methods=['POST'])
@token_required
def mark_all_read(current_user):
    """Clear the badge."""
    try:
        with db.get_db() as session:
            updated = (session.query(Notification)
                       .filter_by(user_id=current_user['user_id'])
                       .filter(Notification.read_at.is_(None))
                       .update({'read_at': datetime.utcnow()}, synchronize_session=False))
            return jsonify({'message': 'All marked as read', 'count': updated}), 200
    except Exception as e:
        logger.error(f"Mark all read error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

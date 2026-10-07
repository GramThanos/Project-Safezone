"""Browser push subscriptions for the signed-in account."""
import logging

from flask import Blueprint, request, jsonify

from src.database import db
from src.middleware.auth import token_required
from src.models.push_subscription import PushSubscription
from src.models.scheduled_job import ScheduledJob
from src.utils import daily, push, settings

logger = logging.getLogger(__name__)
push_bp = Blueprint('push', __name__, url_prefix='/api/push')


@push_bp.route('/key', methods=['GET'])
@token_required
def key(current_user):
    """What a browser needs to subscribe, and whether reminders are being sent.

    The reminder's state comes along so the profile can say "reminders are not
    switched on here" rather than let somebody subscribe to silence.
    """
    public_key = push.public_key()
    if not public_key:
        return jsonify({'error': 'Notifications are unavailable right now'}), 503
    try:
        with db.get_db() as session:
            job = session.query(ScheduledJob).filter_by(kind='crate_reminder').first()
            enabled = bool(job and job.enabled)
        return jsonify({
            'public_key': public_key,
            'reminder': {
                'enabled': enabled,
                'time': settings.get('crate_reminder_time'),
                'timezone': str(daily.primary_timezone()),
            },
        }), 200
    except Exception as e:
        logger.error(f"Push key error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@push_bp.route('/subscriptions', methods=['POST'])
@token_required
def subscribe(current_user):
    """Store this device's subscription (the browser's `PushSubscription.toJSON()`).

    Also how a device is re-bound after signing in again: the browser still has
    its subscription, and posting it here ties it to the new session.

    Only shape-checked here. Whether the endpoint is a push service we will
    send to is the game-server's call, made at send time; one it refuses is
    reported `invalid` and deleted then.
    """
    data = request.get_json(silent=True) or {}
    endpoint = data.get('endpoint')
    keys = data.get('keys') if isinstance(data.get('keys'), dict) else {}
    if not isinstance(endpoint, str) or not endpoint.startswith('https://') or len(endpoint) > 1024:
        return jsonify({'error': 'Not a push subscription'}), 400

    def key_value(name, limit):
        value = keys.get(name)
        return value if isinstance(value, str) and len(value) <= limit else None

    try:
        with db.get_db() as session:
            digest = PushSubscription.hash_endpoint(endpoint)
            row = session.query(PushSubscription).filter_by(endpoint_hash=digest).first()
            if row is None:
                row = PushSubscription(endpoint_hash=digest, endpoint=endpoint)
                session.add(row)
            # A device belongs to whoever subscribed from it last, for as long
            # as the session they did it in lasts.
            row.user_id = current_user['user_id']
            push.bind(row, current_user)
            row.p256dh = key_value('p256dh', 128)
            row.auth = key_value('auth', 64)
        return jsonify({'message': 'Reminders are on for this device'}), 201
    except Exception as e:
        logger.error(f"Push subscribe error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@push_bp.route('/subscriptions', methods=['DELETE'])
@token_required
def unsubscribe(current_user):
    """Forget this device's subscription. Idempotent."""
    data = request.get_json(silent=True) or {}
    endpoint = data.get('endpoint')
    if not isinstance(endpoint, str):
        return jsonify({'error': 'endpoint is required'}), 400
    try:
        with db.get_db() as session:
            (session.query(PushSubscription)
             .filter_by(endpoint_hash=PushSubscription.hash_endpoint(endpoint),
                        user_id=current_user['user_id'])
             .delete(synchronize_session=False))
        return jsonify({'message': 'Reminders are off for this device'}), 200
    except Exception as e:
        logger.error(f"Push unsubscribe error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

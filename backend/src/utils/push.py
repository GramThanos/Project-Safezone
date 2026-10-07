"""Browser push notifications: the backend's half.

The backend decides who hears what; the game-server sends it (`POST /api/push`),
because this container has no egress - the same split as Discord and mail.

Pushes carry no payload, so the text a device shows lives in the frontend's
service worker (`frontend/public/sw.js`). That keeps the sending side to a
signature rather than message encryption; see `game-server/src/push.py`.

Grouping: one relay call carries a whole batch of devices, and the game-server
shares signatures and connections within it. Web Push itself has no batch call.
"""
import logging
from datetime import datetime, time, timedelta

from src.models.push_subscription import PushSubscription
from src.utils import settings
from src.utils.game_server import gs_request

logger = logging.getLogger(__name__)

# Devices per relay call: under the game-server's PUSH_MAX_BATCH, and small
# enough for one call to finish well inside its timeout.
BATCH = 500
RELAY_TIMEOUT = 120

# How long after the reminder time a reminder may still go out. A scheduler
# that was down at 18:00 should remind at 18:20, not at 23:50.
LATE_WINDOW = timedelta(hours=3)


def parse_time(value):
    """``'HH:MM'`` (24-hour) as a ``time``, or None if it is not one."""
    if not isinstance(value, str):
        return None
    parts = value.strip().split(':')
    if len(parts) != 2 or not all(p.isdigit() and len(p) == 2 for p in parts):
        return None
    hour, minute = int(parts[0]), int(parts[1])
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def validate_time(value):
    """Settings validator for the reminder time."""
    if parse_time(value) is None:
        return 'Use 24-hour HH:MM, for example 18:00.'
    return None


def reminder_due(now_local, at):
    """Whether ``now_local`` is inside today's reminder window.

    From the reminder time until ``LATE_WINDOW`` after it, and never past
    midnight - the day the reminder is about ends there.
    """
    start = now_local.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
    return start <= now_local < start + LATE_WINDOW


def seconds_until_midnight(now_local):
    """How long a reminder stays worth delivering: until the day it is about ends.

    Passed as the push's TTL, so a phone that is off until tomorrow does not
    wake up to news about yesterday's crate.
    """
    midnight = datetime.combine(now_local.date() + timedelta(days=1), time(0),
                                tzinfo=now_local.tzinfo)
    return max(60, int((midnight - now_local).total_seconds()))


def vapid_subject():
    """The contact push services are given: the site's address when it is https.

    Otherwise None, and the game-server uses its own PUSH_SUBJECT.
    """
    url = (settings.get('site_url') or '').strip()
    return url if url.startswith('https://') else None


def public_key():
    """The VAPID public key from the game-server, or None if it is unreachable."""
    payload, status = gs_request('GET', '/api/push/key')
    if status != 200:
        return None
    return (payload.get('data') or {}).get('public_key')


def send(endpoints, ttl, topic):
    """Push to every endpoint, in relay-sized batches.

    Returns ``{endpoint: result}``, where result is the game-server's verdict
    (``ok`` / ``gone`` / ``invalid`` / ``failed``). A batch the game-server
    could not take is ``failed`` throughout.
    """
    outcomes = {}
    subject = vapid_subject()
    for start in range(0, len(endpoints), BATCH):
        chunk = endpoints[start:start + BATCH]
        payload, status = gs_request('POST', '/api/push', json={
            'endpoints': chunk,
            'ttl': ttl,
            'topic': topic,
            'subject': subject,
        }, timeout=RELAY_TIMEOUT)
        results = (payload.get('data') or {}).get('results') if status == 200 else None
        if not isinstance(results, list) or len(results) != len(chunk):
            logger.error(f"Push relay refused a batch of {len(chunk)} ({status}): "
                         f"{payload.get('error')}")
            outcomes.update({endpoint: 'failed' for endpoint in chunk})
            continue
        for endpoint, result in zip(chunk, results):
            outcomes[endpoint] = result.get('result') if isinstance(result, dict) else 'failed'
    return outcomes


def extend_session(session, sid, expires_at):
    """Carry a refreshed session's new expiry to the subscriptions made in it."""
    if not sid:
        return 0
    return (session.query(PushSubscription)
            .filter_by(session_id=sid)
            .update({'session_expires_at': expires_at}, synchronize_session=False))


def bind(row, current_user):
    """Tie a subscription to the session of the token that created it."""
    from src.middleware.auth import session_id

    row.session_id = session_id(current_user)
    row.session_expires_at = datetime.utcfromtimestamp(current_user['exp'])
    row.token_version = int(current_user.get('tv') or 0)


def record(session, outcomes):
    """Forget dead subscriptions and stamp the ones that worked.

    ``gone`` is the push service saying the device unsubscribed; ``invalid`` is
    an endpoint the game-server will never send to. Neither will ever work, so
    both are deleted. Returns ``(sent, removed)``.
    """
    dead = [PushSubscription.hash_endpoint(e) for e, r in outcomes.items() if r in ('gone', 'invalid')]
    sent = [PushSubscription.hash_endpoint(e) for e, r in outcomes.items() if r == 'ok']
    removed = 0
    if dead:
        removed = (session.query(PushSubscription)
                   .filter(PushSubscription.endpoint_hash.in_(dead))
                   .delete(synchronize_session=False))
    if sent:
        (session.query(PushSubscription)
         .filter(PushSubscription.endpoint_hash.in_(sent))
         .update({'last_sent_at': datetime.utcnow()}, synchronize_session=False))
    return len(sent), removed

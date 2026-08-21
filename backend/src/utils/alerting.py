"""What the site can announce to staff, and the cooldown that keeps it readable.

Before this, "something happened, tell somebody" existed three times over: an
in-app notification written at the call site, a mail path used only for account
tokens, and a Discord relay with its own event list. Three lists of things worth
saying, none of which knew about the others, and no screen where an operator
could see the whole set.

So: **one registry of events, one dispatcher, and channels as rows in a table.**
A channel is a place messages go - a Discord webhook, the staff inbox, an ops
mailbox - and it subscribes to the events it wants. Adding a fourth kind of
channel later means writing one sender, not a fourth event list.

**This is the staff-facing half only.** Messages addressed to a *player* about
their own account - your reward arrived, your ban has ended - are not routable
and are not here; they go to the person concerned through `notify.py`, as they
always did. The same goes for account mail (verification, password reset), which
carries a one-time token and is a mechanism rather than an announcement. Neither
belongs in a grid where an operator can switch it off.

**Two sources of events.** Anything the backend knows is emitted at its call
site by `emit()`. Anything only the game-server can see - a player joining, a
server dying - is pushed onto a Redis queue by the manager and drained by the
scheduler's pump, because the manager must never call the backend; that
dependency runs one way and stays that way.

**Announcing must never break the thing being announced.** Everything here
swallows its failures, and `emit()` does the work on a background thread so a
slow Discord never becomes a slow signup.
"""
import json
import logging
import threading
from datetime import datetime

from flask import current_app, has_app_context

from src.database import db
from src.models.alert_channel import AlertChannel
from src.utils import channels
from src.utils.redis_utils import get_redis_connection

logger = logging.getLogger(__name__)

# Discord embed colours, as the decimal integers its API wants. Kept here rather
# than in the sender because they are a property of the event ("this is bad
# news"), not of the transport.
GREEN = 0x2ECC71
GREY = 0x95A5A6
RED = 0xE74C3C
AMBER = 0xF1C40F
BLURPLE = 0x5865F2

# Where the game-server manager leaves events it saw. Must match
# `game-server/src/config.py::WEBHOOK_EVENT_QUEUE`.
QUEUE_KEY = 'webhook:events'
# When the pump last looked, so the panel can say "nothing is draining this"
# rather than leaving an operator to wonder why the channels are quiet.
PUMP_KEY = 'webhook:pump:at'
# Queued events older than this are dropped rather than announced. "Somebody
# joined" stops being news quickly, and a scheduler that was down for half an
# hour coming back with half an hour of arrivals is worse than silence.
MAX_EVENT_AGE_SECONDS = 600

# How many consecutive failures before a channel is switched off. A Discord
# webhook that has been deleted answers 404 forever, and retrying it on every
# join is noise in the log for something nobody is reading.
FAILURE_LIMIT = 10

# The cooldown gate lives here too - see `should_fire`. It is keyed per
# condition, not per channel: "this is already known" is a fact about the
# problem, and letting Discord and the staff inbox fall out of step over it
# would make two accounts of the same outage that disagree about when it began.
COOLDOWN_PREFIX = 'alert:'

# The event catalog.
#
#   group    how the panel arranges the checkboxes
#   scoped   happens on a particular server, so the per-channel server filter
#            applies to it
#   source   'game' events arrive through the queue; 'site' ones from a call site
#   volume   'high' means it fires per player action - fine for a Discord
#            channel, a poor idea for a mailbox, and the panel says so
EVENTS = {
    'player.join': {
        'group': 'Game', 'source': 'game', 'scoped': True, 'color': GREEN,
        'volume': 'high',
        'label': 'Player joins a server',
        'help': 'Someone connected. The in-game character name is sent.',
    },
    'player.leave': {
        'group': 'Game', 'source': 'game', 'scoped': True, 'color': GREY,
        'volume': 'high',
        'label': 'Player leaves a server',
        'help': 'Someone disconnected.',
    },
    'server.state': {
        'group': 'Game', 'source': 'game', 'scoped': True, 'color': BLURPLE,
        'label': 'Server starts, sleeps or stops',
        'help': 'Every change of a running state, including waking on demand.',
    },
    'server.failed': {
        'group': 'Game', 'source': 'game', 'scoped': True, 'color': RED,
        'label': 'Server gives up starting',
        'help': 'It wanted to be up and could not stay up. Worth waking somebody for.',
    },
    'character.linked': {
        'group': 'Accounts', 'scoped': True, 'color': GREEN,
        'label': 'Character linked to an account',
        'help': 'A claim passed the online check and the link was made.',
    },
    'character.revoked': {
        'group': 'Accounts', 'scoped': True, 'color': AMBER,
        'label': 'Character link revoked by staff',
    },
    'user.signup': {
        'group': 'Accounts', 'color': BLURPLE,
        'label': 'New account registered',
        'help': 'The username only - email addresses are never announced.',
    },
    'user.banned': {
        'group': 'Moderation', 'color': RED,
        'label': 'Account banned',
    },
    'user.unbanned': {
        'group': 'Moderation', 'color': GREEN,
        'label': 'Ban lifted',
        'help': 'Whether a person lifted it or it simply expired.',
    },
    'report.created': {
        'group': 'Moderation', 'color': AMBER,
        'label': 'Report or appeal submitted',
        'help': 'The staff inbox and ops mail see the opening lines; a Discord '
                'channel gets only who filed it and about whom.',
    },
    'reward.delivered': {
        'group': 'Loot', 'color': GREEN, 'volume': 'high',
        'label': 'Reward delivered in game',
        'help': 'One message per item sent.',
    },
    'reward.failed': {
        'group': 'Loot', 'color': AMBER,
        'label': 'Reward came back undelivered',
    },
    'alert.raised': {
        'group': 'Operations', 'color': RED,
        'label': 'Operational alert',
        'help': 'A server that has been given up on, an unreachable game-server, '
                'or deliveries failing in bulk. Cooled down so the channel stays '
                'worth reading.',
    },
}

# Panel ordering. Groups not listed here fall to the end alphabetically.
GROUP_ORDER = ['Game', 'Accounts', 'Moderation', 'Loot', 'Operations']


def describe():
    """The catalog, for the admin panel."""
    def sort_key(item):
        key, spec = item
        group = spec.get('group', '')
        index = GROUP_ORDER.index(group) if group in GROUP_ORDER else len(GROUP_ORDER)
        return (index, group, key)

    return [{
        'key': key,
        'group': spec.get('group', 'Other'),
        'label': spec.get('label', key),
        'help': spec.get('help'),
        'scoped': bool(spec.get('scoped')),
        'source': spec.get('source', 'site'),
        'volume': spec.get('volume', 'low'),
    } for key, spec in sorted(EVENTS.items(), key=sort_key)]


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------

def should_fire(key, cooldown_seconds):
    """Whether this condition is new enough to be worth saying out loud.

    Uses SET NX EX, so two schedulers racing produce one alert rather than two.
    Fails *open* - if Redis is unreachable the alert still goes out, because a
    duplicate message is a much smaller problem than a silent outage.
    """
    try:
        client = get_redis_connection()
        return bool(client.set(f'{COOLDOWN_PREFIX}{key}', '1',
                               nx=True, ex=max(60, int(cooldown_seconds))))
    except Exception as e:
        logger.error(f"Could not check alert cooldown for {key}: {e}")
        return True


def clear(key):
    """Forget a condition, so recovery re-arms it."""
    try:
        get_redis_connection().delete(f'{COOLDOWN_PREFIX}{key}')
    except Exception as e:
        logger.error(f"Could not clear alert {key}: {e}")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def _record(channel, ok, error, status=None):
    """Write the outcome onto the channel, and retire one that is gone for good."""
    channel.last_sent_at = datetime.utcnow()
    channel.last_status = 'ok' if ok else 'failed'
    channel.last_error = None if ok else error
    if ok:
        channel.failure_count = 0
    else:
        channel.failure_count = (channel.failure_count or 0) + 1
        # 401/403/404 from Discord mean the webhook itself is gone or was
        # revoked. That is not transient and will not fix itself, so stop.
        gone = status in (401, 403, 404)
        if gone or channel.failure_count >= FAILURE_LIMIT:
            channel.enabled = False
            channel.last_error = (f'{error} - switched off after '
                                  f'{channel.failure_count} failure(s)')


def dispatch(event, title, description=None, detail=None, fields=None,
             server_id=None, link=None):
    """Send one event to every channel subscribed to it. Needs an app context.

    ``detail`` is for internal channels only - the staff inbox and ops mail get
    it, an external channel never does. That is what lets one event carry the
    opening lines of a report to the moderators who act on it while the Discord
    copy says only that a report exists.

    Synchronous: callers serving a request should use `emit` instead. Returns
    the number of channels that accepted the message.
    """
    if event not in EVENTS:
        logger.error(f"Refusing to dispatch unknown alert event '{event}'")
        return 0

    spec = EVENTS[event]
    message = {
        'event': event,
        'title': title,
        'description': description,
        'detail': detail,
        'fields': [(name, value) for name, value in (fields or [])
                   if value not in (None, '')],
        'link': link,
        'color': spec.get('color', BLURPLE),
    }

    sent = 0
    try:
        with db.get_db() as session:
            rows = [row for row in session.query(AlertChannel).all()
                    if row.wants(event, server_id)]
            for row in rows:
                ok, error, status = channels.deliver(session, row, message)
                _record(row, ok, error, status)
                if ok:
                    sent += 1
                else:
                    logger.warning(f"Alert channel '{row.name}' failed for {event}: {error}")
    except Exception as e:
        # Announcing a thing must never break the thing.
        logger.error(f"Alert dispatch for '{event}' failed: {e}")
    return sent


def emit(event, title, description=None, detail=None, fields=None,
         server_id=None, link=None):
    """Fire and forget, from a request handler or a job.

    The work happens on a daemon thread holding its own app context, so a
    Discord that takes three seconds does not add three seconds to somebody's
    signup. Nothing is returned, and nothing is raised.
    """
    if not has_app_context():
        logger.error(f"Alert event '{event}' emitted without an app context")
        return

    app = current_app._get_current_object()

    def run():
        try:
            with app.app_context():
                dispatch(event, title, description=description, detail=detail,
                         fields=fields, server_id=server_id, link=link)
        except Exception as e:
            logger.error(f"Alert thread for '{event}' failed: {e}")

    threading.Thread(target=run, name=f'alert-{event}', daemon=True).start()


def send_test(channel_id):
    """Post a sample message to one channel. Returns ``(ok, error)``.

    Synchronous and reported back, unlike a real event: somebody who has just
    pasted a webhook URL or typed an address is waiting to be told whether it
    works, and "it went into a thread, good luck" is not an answer. Ignores
    `enabled` and the subscription list - testing before switching on is the
    normal order.
    """
    try:
        with db.get_db() as session:
            row = session.query(AlertChannel).filter_by(id=channel_id).first()
            if not row:
                return False, 'No such channel'

            subscribed = len(row.events or [])
            message = {
                'event': 'test',
                'title': 'Alert test',
                'description': 'If you can read this, alerts from the panel '
                               'will arrive here.',
                'detail': None,
                'fields': [('Subscribed events', subscribed or 'none')],
                'link': '/admin/alerts',
                'color': BLURPLE,
            }
            ok, error, _status = channels.deliver(session, row, message)
            # A test counts - same destination, same relay - but a failing one
            # must not count towards the auto-off threshold, or somebody fixing
            # a URL would switch their own channel off by trying.
            row.last_sent_at = datetime.utcnow()
            row.last_status = 'ok' if ok else 'failed'
            row.last_error = None if ok else error
            if ok:
                row.failure_count = 0
            return ok, error
    except Exception as e:
        logger.error(f"Alert test for {channel_id} failed: {e}")
        return False, 'Could not send the test message'


def any_subscribers():
    """Whether any enabled channel exists at all.

    The pump asks first: with nothing configured there is no reason to touch the
    queue, and that is the common case for most deployments.
    """
    try:
        with db.get_db() as session:
            return session.query(AlertChannel).filter(
                AlertChannel.enabled.is_(True)).count() > 0
    except Exception as e:
        logger.error(f"Could not count alert channels: {e}")
        return False


# ---------------------------------------------------------------------------
# The queue of things the game-server saw
# ---------------------------------------------------------------------------

def _render(entry):
    """Turn a queued game event into a message. Returns ``(title, description, fields)``."""
    event = entry.get('event')
    server = entry.get('server_name') or f"server {entry.get('server_id')}"
    player = entry.get('player')

    if event == 'player.join':
        return f'{player} joined {server}', None, [('Online now', entry.get('online'))]
    if event == 'player.leave':
        return f'{player} left {server}', None, [('Online now', entry.get('online'))]
    if event == 'server.state':
        state = entry.get('state')
        words = {
            'running': 'is up',
            'sleeping': 'went to sleep and will wake when someone connects',
            'stopped': 'stopped',
            'failed': 'is in trouble',
        }
        return (f"{server} {words.get(state, f'is now {state}')}",
                None, [('State', state), ('Was', entry.get('previous'))])
    if event == 'server.failed':
        return (f'{server} keeps failing to start',
                'The manager has stopped retrying. Check the server log for why.',
                None)

    # An event kind this version does not know how to phrase. Say something
    # rather than dropping it silently.
    return f'{server}: {event}', None, None


def _too_old(timestamp):
    """Whether a queued event has been waiting long enough to be misleading."""
    if not timestamp:
        return False
    try:
        when = datetime.strptime(timestamp.rstrip('Z')[:26], '%Y-%m-%dT%H:%M:%S.%f')
    except (TypeError, ValueError):
        return False
    return (datetime.utcnow() - when).total_seconds() > MAX_EVENT_AGE_SECONDS


def discard():
    """Throw the queue away, for when nothing is subscribed to any of it.

    Without this, configuring the very first channel would immediately replay
    whatever had piled up while there was nobody to tell.
    """
    try:
        client = get_redis_connection()
        if client is not None:
            client.delete(QUEUE_KEY)
    except Exception as e:
        logger.debug(f"Could not clear the alert queue: {e}")


def drain(limit=200):
    """Send whatever the game-server has queued. Returns how many were handled.

    Oldest first. The queue is capped at the writing end, so a backend that was
    down for an hour comes back to the most recent events rather than an hour of
    backlog - stale player-join messages are worse than no message.
    """
    client = get_redis_connection()
    if client is None:
        return 0

    handled = 0
    try:
        for _ in range(max(1, int(limit))):
            raw = client.rpop(QUEUE_KEY)
            if raw is None:
                break
            handled += 1
            try:
                entry = json.loads(raw)
            except (TypeError, ValueError):
                logger.warning('Dropped an unreadable alert queue entry')
                continue

            event = entry.get('event')
            if event not in EVENTS:
                logger.warning(f"Dropped an alert queue entry for unknown event '{event}'")
                continue
            if _too_old(entry.get('ts')):
                continue

            title, description, fields = _render(entry)
            dispatch(event, title, description=description, fields=fields,
                     server_id=entry.get('server_id'), link='/admin/servers')
    except Exception as e:
        logger.error(f"Draining the alert queue failed: {e}")
    return handled


def pump_seen():
    """Record that the pump ran, for the panel's "is this working" line."""
    try:
        client = get_redis_connection()
        if client is not None:
            client.set(PUMP_KEY, datetime.utcnow().isoformat(), ex=3600)
    except Exception as e:
        logger.debug(f"Could not record the alert pump heartbeat: {e}")


def pump_status():
    """Queue depth and how long ago the scheduler last drained it.

    The age is computed here rather than in the browser: these timestamps are
    naive UTC, and a browser that reads one as local time would report a pump
    running fine as hours stale, or the reverse.
    """
    status = {'queued': None, 'last_pump_at': None, 'age_seconds': None}
    try:
        client = get_redis_connection()
        if client is None:
            return status
        status['queued'] = client.llen(QUEUE_KEY)
        last = client.get(PUMP_KEY)
        status['last_pump_at'] = last
        if last:
            try:
                seen = datetime.strptime(last.rstrip('Z')[:26], '%Y-%m-%dT%H:%M:%S.%f')
                status['age_seconds'] = int((datetime.utcnow() - seen).total_seconds())
            except (TypeError, ValueError):
                pass
    except Exception as e:
        logger.error(f"Could not read the alert queue status: {e}")
    return status

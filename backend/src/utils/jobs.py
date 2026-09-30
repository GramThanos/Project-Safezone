"""The job handlers the scheduler can run.

A handler takes a session and its job's params, and returns a short string
describing what it did - that string lands in `last_result` and is the only
thing an operator sees, so make it specific ("granted 4 bonus boxes", not "ok").

Handlers must be safe to run twice. The scheduler tries not to double-run them,
but a restart at the wrong moment can always happen, so the guarantee has to
come from the work itself: every handler here is guarded by a uniqueness
constraint or an idempotent filter.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import func

from src.models.audit_log import AuditLog
from src.models.notification import Notification
from src.models.user import User
from src.models.user_box import UserBox
from src.utils import alerting, daily, expiry, notify, settings

logger = logging.getLogger(__name__)

REGISTRY = {}


def job(kind, default_interval, description):
    """Register a handler under a job kind."""
    def wrap(fn):
        REGISTRY[kind] = {
            'run': fn,
            'default_interval': default_interval,
            'description': description,
        }
        return fn
    return wrap


# ---------------------------------------------------------------------------

@job('weekly_streak_bonus', 3600,
     'Grant a bonus loot box to accounts that collected enough daily boxes last week')
def weekly_streak_bonus(session, params=None):
    """Pay the streak bonus for the week that has just ended.

    Runs hourly and does nothing most of the time: the work is keyed to a
    completed week, and the uniqueness constraint on
    (user_id, event_id, period_key) makes a repeat run a no-op rather than a
    double payout. The box granted is a weighted pick from the weekly-bonus
    event's line-up.
    """
    from src.models.event import Event
    from src.utils import events, loot

    event = events.system_event(session, Event.TYPE_WEEKLY_BONUS)
    if not event or not event.enabled:
        return 'skipped: the weekly bonus event is switched off'

    threshold = settings.get('streak_threshold') or 5

    # The bonus event's box line-up, read once; each eligible account gets its
    # own weighted pick from it.
    entries = events.event_box_entries(session, event.id)
    if not entries:
        return 'skipped: the weekly bonus event has no box that can drop'

    # "Last week" in the primary server's timezone, so the boundary matches the
    # one players already experience for the daily reset.
    today = daily.today()
    week_end = today - timedelta(days=today.isoweekday())      # the most recent Sunday
    week_start = week_end - timedelta(days=6)                  # its Monday
    period_key = week_end.isoformat()

    # Accounts with enough distinct daily grants inside that window.
    rows = (session.query(UserBox.user_id,
                          func.count(func.distinct(UserBox.grant_date)).label('days'))
            .filter(UserBox.source == UserBox.SOURCE_DAILY,
                    UserBox.grant_date >= week_start,
                    UserBox.grant_date <= week_end)
            .group_by(UserBox.user_id)
            .having(func.count(func.distinct(UserBox.grant_date)) >= threshold)
            .all())

    granted = 0
    for user_id, days in rows:
        already = (session.query(UserBox)
                   .filter_by(user_id=user_id, event_id=event.id, period_key=period_key)
                   .first())
        if already:
            continue

        box_id = loot.pick_weighted(entries)
        if box_id is None:
            continue

        session.add(UserBox(user_id=user_id, box_id=box_id, event_id=event.id,
                            source=UserBox.SOURCE_BONUS, period_key=period_key,
                            grant_date=week_end, expires_at=expiry.box_deadline()))
        notify.send(session, user_id, Notification.KIND_LOOT,
                    'You earned a weekly bonus box',
                    body=f'You collected {days} of 7 daily boxes last week. '
                         f'Your bonus is waiting to be opened.',
                    link='/rewards')
        granted += 1

    if not rows:
        return f'no accounts reached {threshold}/7 for the week ending {week_end}'
    return f'granted {granted} bonus box(es) for the week ending {week_end}'


@job('expire_loot', 3600, 'Expire unopened boxes and unsent rewards past their deadline')
def expire_loot(session, params=None):
    """Void loot that was never collected.

    Marked expired rather than deleted: a player should be able to see what they
    let lapse, and the record of what was granted stays intact for the audit of
    the economy.
    """
    from src.models.inventory_item import InventoryItem

    now = datetime.utcnow()

    boxes = (session.query(UserBox)
             .filter(UserBox.status == UserBox.STATUS_UNOPENED,
                     UserBox.expires_at.isnot(None),
                     UserBox.expires_at <= now)
             .update({'status': UserBox.STATUS_EXPIRED}, synchronize_session=False))

    # Only items still sitting in the player's hands: anything mid-delivery is
    # the reconciler's business, and a delivered reward is already gone.
    items = (session.query(InventoryItem)
             .filter(InventoryItem.status == InventoryItem.STATUS_HELD,
                     InventoryItem.expires_at.isnot(None),
                     InventoryItem.expires_at <= now)
             .update({'status': InventoryItem.STATUS_EXPIRED}, synchronize_session=False))

    if not boxes and not items:
        return 'nothing had expired'
    return f'expired {boxes} box(es) and {items} unsent reward(s)'


@job('expire_bans', 900, 'Restore accounts whose timed ban has run out')
def expire_bans(session, params=None):
    """Lift timed bans that have run their course.

    Restores the role the account held before the ban rather than assuming
    everyone was a plain player - demoting a moderator by way of a week's ban
    would be a quiet, lasting mistake.

    Returns a deferred callable for the in-game unbans: those are HTTP calls to
    the game-server, and running them inside this transaction would hold it open
    for as long as the other service takes.
    """
    from src.models.ban import Ban
    from src.utils import moderation

    now = datetime.utcnow()
    due = (session.query(Ban)
           .filter(Ban.lifted_at.is_(None),
                   Ban.expires_at.isnot(None),
                   Ban.expires_at <= now)
           .all())
    if not due:
        return 'no bans had expired'

    restored = []
    pending = []      # in-game unbans, run after this transaction closes
    for ban in due:
        user = session.query(User).filter_by(id=ban.user_id).first()
        if not user:
            ban.lifted_at = now
            continue

        user.role = ban.prior_role or User.ROLE_PLAYER
        ban.lifted_at = now
        ban.lifted_by = None  # lifted by the clock, not a person

        notify.send(session, user.id, Notification.KIND_MODERATION,
                    'Your ban has ended',
                    body=f'You can sign in again. Your role is {user.role}.')
        alerting.emit('user.unbanned', f"{user.username}'s ban has expired",
                      fields=[('Account', user.username), ('Role', user.role)])

        pending.extend(moderation.targets(session, user.id))
        restored.append(user.username)

    summary = f"lifted {len(restored)} ban(s): {', '.join(restored) or 'none'}"
    if not pending:
        return summary
    return summary, lambda: moderation.lift_ban(pending)


@job('track_characters', 300, 'Record when each linked character was last seen online')
def track_characters(session, params=None):
    """Stamp `last_seen_at` from the online rosters the manager publishes.

    Cheap: the rosters are already in the cache, so this is a read per server
    and one update per player actually online.
    """
    from src.models.character import Character
    from src.utils.game_server import gs_request
    from src.utils.redis_utils import get_online_players

    payload, status = gs_request('GET', '/api/servers')
    if status != 200:
        return 'skipped: could not reach the game-server'

    now = datetime.utcnow()
    seen = 0
    for server in payload.get('data') or []:
        online = get_online_players(server.get('id'))
        if not online:
            continue
        seen += (session.query(Character)
                 .filter(Character.server_id == server.get('id'),
                         Character.in_game_username.in_(list(online)))
                 .update({'last_seen_at': now}, synchronize_session=False))

    return f'stamped {seen} character(s) as seen just now'


@job('flag_dormant_links', 86400, 'Tell owners when a character link looks abandoned')
def flag_dormant_links(session, params=None):
    """Warn the owner of a link that has not been seen for a long time.

    Deliberately does **not** unlink. Releasing someone's in-game name without
    asking is taking something away; telling them it looks abandoned lets them
    keep it or free it themselves, and staff can still revoke.
    """
    from src.models.character import Character

    days = settings.get('dormant_link_days') or 0
    if days <= 0:
        return 'skipped: dormancy warnings are switched off'

    cutoff = datetime.utcnow() - timedelta(days=days)
    stale = (session.query(Character)
             .filter(Character.verified.is_(True),
                     Character.last_seen_at.isnot(None),
                     Character.last_seen_at < cutoff)
             .all())
    if not stale:
        return f'no links unseen for {days} days'

    warned = 0
    for character in stale:
        # Redis holds the "already told them" flag, so this can run daily
        # without becoming a daily nag.
        if not alerting.should_fire(f'dormant:{character.id}', 86400 * max(1, days // 2)):
            continue
        notify.send(session, character.user_id, Notification.KIND_CLAIM,
                    f'{character.in_game_username} has not been seen in a while',
                    body=f'It was last online {character.last_seen_at:%d %b %Y}. '
                         f'If you no longer play it, unlinking frees the name for '
                         f'someone else.',
                    link='/characters')
        warned += 1

    return f'{len(stale)} dormant link(s), warned {warned}'


@job('check_alerts', 900, 'Alert staff about servers that are down or deliveries failing')
def check_alerts(session, params=None):
    """Look at what the system already knows and say something when it is bad.

    Detection only. Where an alert goes - the staff feed, a Discord channel, an
    ops mailbox - is configured per channel in Admin > Alerts; this job decides
    *whether there is anything to say*, and the cooldown makes that decision
    once for every channel rather than per destination, so two channels never
    disagree about when an outage started.
    """
    from src.models.inventory_item import InventoryItem
    from src.utils.game_server import gs_request
    from src.utils.redis_utils import apply_live_state

    if not settings.get('alerts_enabled'):
        return 'skipped: alerts are switched off'

    cooldown = (settings.get('alert_cooldown_minutes') or 60) * 60
    raised = []

    payload, status = gs_request('GET', '/api/servers')
    if status != 200:
        if alerting.should_fire('game-server-unreachable', cooldown):
            # Emitted knowing a Discord channel almost certainly will not hear
            # it: Discord is reached *through* the game-server, so the container
            # that cannot be reached is the one that would carry the news. The
            # staff feed and ops mail are unaffected, and it still succeeds for
            # Discord in the case that matters - the manager process wedged
            # while the container itself still answers.
            alerting.emit('alert.raised', 'The game-server manager is unreachable',
                          description='Server control, task processing and reward '
                                      'delivery are all unavailable until it comes back.',
                          link='/admin/servers')
            raised.append('game-server unreachable')
        return '; '.join(raised) or 'game-server unreachable (already reported)'

    # A server the orchestrator gave up on: it wanted to be running and could not
    # stay up. Distinct from "stopped", which somebody asked for.
    try:
        for server in apply_live_state(payload.get('data') or []):
            key = f"server-failed:{server['id']}"
            if server.get('state') == 'failed':
                if alerting.should_fire(key, cooldown):
                    alerting.emit('alert.raised',
                                  f"{server['name']} keeps failing to start",
                                  description='The manager has stopped retrying. '
                                              'Check the server log for why.',
                                  server_id=server.get('id'),
                                  link='/admin/servers')
                    raised.append(f"{server['name']} failed")
            else:
                # Recovered - re-arm so the next failure is heard.
                alerting.clear(key)
    except Exception as e:
        logger.error(f"Alert check could not read server state: {e}")

    # Deliveries failing in bulk usually means the game-server is up but wedged.
    since = datetime.utcnow() - timedelta(hours=1)
    failed = (session.query(InventoryItem)
              .filter(InventoryItem.status == InventoryItem.STATUS_FAILED,
                      InventoryItem.sent_at.isnot(None),
                      InventoryItem.sent_at >= since)
              .count())
    if failed >= 5 and alerting.should_fire('delivery-failures', cooldown):
        alerting.emit('alert.raised', 'Reward deliveries are failing',
                      description=f'{failed} deliveries failed in the last hour. '
                                  f'Players get their items back, but something '
                                  f'is wrong.',
                      link='/admin/tasks')
        raised.append(f'{failed} delivery failures')

    return '; '.join(raised) if raised else 'nothing to report'


@job('prune_audit', 86400, 'Delete audit entries older than the retention window')
def prune_audit(session, params=None):
    """Enforce the audit retention window, if one is configured."""
    days = settings.get('audit_retention_days') or 0
    if days <= 0:
        return 'skipped: audit entries are kept indefinitely'

    cutoff = datetime.utcnow() - timedelta(days=days)
    removed = (session.query(AuditLog)
               .filter(AuditLog.created_at < cutoff)
               .delete(synchronize_session=False))
    return f'removed {removed} audit entr{"y" if removed == 1 else "ies"} older than {days} days'


@job('prune_auth_tokens', 86400, 'Delete spent and expired verification/reset tokens')
def prune_auth_tokens(session, params=None):
    """Tidy one-time tokens once they can no longer be used.

    They are single-use and short-lived, so anything expired or already spent is
    dead weight - and it is credential-adjacent weight, which is worth not
    keeping around.
    """
    from src.models.auth_token import AuthToken

    cutoff = datetime.utcnow() - timedelta(days=7)
    removed = (session.query(AuthToken)
               .filter((AuthToken.expires_at < cutoff) | (AuthToken.used_at < cutoff))
               .delete(synchronize_session=False))
    return f'removed {removed} spent token(s)'


@job('prune_staff_alerts', 86400, 'Delete staff feed entries older than the retention window')
def prune_staff_alerts(session, params=None):
    """Keep the staff feed to its retention window.

    Unlike the audit log, this one has a non-zero default. The feed is
    operational - what fired, and is anything flowing - not a record of who did
    what, so a month-old "player joined" has no value to anybody and the feed
    fills fastest from exactly those high-volume events. Set the window to 0 to
    keep everything anyway.
    """
    from src.models.staff_alert import StaffAlert

    days = settings.get('staff_alert_retention_days') or 0
    if days <= 0:
        return 'skipped: staff feed entries are kept indefinitely'

    cutoff = datetime.utcnow() - timedelta(days=days)
    removed = (session.query(StaffAlert)
               .filter(StaffAlert.created_at < cutoff)
               .delete(synchronize_session=False))
    return f'removed {removed} staff feed entr{"y" if removed == 1 else "ies"} older than {days} days'


@job('server_maintenance', 86400, 'Queue a maintenance task on a game server')
def server_maintenance(session, params=None):
    """Queue a recurring task against the game-server.

    Params: `action` (a game-server task action, e.g. `update_server`) and
    optionally `warn_minutes` to broadcast a warning first.

    Deliberately thin: the game-server owns tasks, so this creates one and lets
    the existing worker do the job rather than reaching across the boundary.
    """
    from src.utils.game_server import gs_request

    params = params or {}
    action = params.get('action')
    if not action:
        return 'skipped: no action configured'

    warn_minutes = params.get('warn_minutes')
    server_id = params.get('server_id')
    if warn_minutes and server_id:
        gs_request('POST', f'/api/servers/{server_id}/command', json={
            'command': f'servermsg "Server maintenance in {warn_minutes} minutes."'
        })

    payload, status = gs_request('POST', '/api/tasks', json={'action': action})
    if status not in (200, 201):
        raise RuntimeError(f"game-server refused the task: {payload.get('error')}")
    task = payload.get('data') or {}
    return f"queued {action} as task {task.get('id')}"


def describe():
    """Every registered kind, for the admin panel."""
    return [
        {'kind': kind, 'description': spec['description'],
         'default_interval': spec['default_interval']}
        for kind, spec in sorted(REGISTRY.items())
    ]

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
from src.utils import alerting, daily, notify, settings

logger = logging.getLogger(__name__)

REGISTRY = {}

# A snapshot may wait for the game to save before it reads, so it is given far
# longer than an ordinary request to the game-server.
SNAPSHOT_TIMEOUT = 90


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
     'Catch up on weekly bonus boxes earned last week but not paid when they were earned')
def weekly_streak_bonus(session, params=None):
    """Pay any streak bonus for the week just ended that was missed at claim time.

    The bonus is normally granted by the daily claim that collects the
    threshold-th box (`events.grant_weekly_bonus`). This is the backstop for a
    week whose last claim could not pay it - the bonus event was switched off or
    had no droppable box at that moment. Both paths share the period key, so
    anything already paid is skipped rather than paid twice.
    """
    from src.models.event import Event
    from src.utils import events

    event = events.system_event(session, Event.TYPE_WEEKLY_BONUS)
    if not event or not event.enabled:
        return 'skipped: the weekly bonus event is switched off'

    threshold = settings.get('streak_threshold') or 5

    # "Last week" in the primary server's timezone, so the boundary matches the
    # one players already experience for the daily reset.
    today = daily.today()
    week_start, week_end = events.week_of(today - timedelta(days=7))

    # Accounts with enough distinct daily grants inside that window.
    rows = (session.query(UserBox.user_id)
            .filter(UserBox.source == UserBox.SOURCE_DAILY,
                    UserBox.grant_date >= week_start,
                    UserBox.grant_date <= week_end)
            .group_by(UserBox.user_id)
            .having(func.count(func.distinct(UserBox.grant_date)) >= threshold)
            .all())

    granted = sum(1 for (user_id,) in rows
                  if events.grant_weekly_bonus(session, user_id, week_end, threshold))

    if not rows:
        return f'no accounts reached {threshold}/7 for the week ending {week_end}'
    return f'granted {granted} missed bonus box(es) for the week ending {week_end}'


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


@job('prune_coin_log', 86400,
     'Delete coin history and shop purchase records older than the retention window')
def prune_coin_log(session, params=None):
    """Keep the coin log and the purchase records to their retention window.

    Both are history rather than state: every total anything shows is a counter
    on the row it describes, so trimming them changes no balance, no
    "earned so far" and no listing's sales count. A daily limit reads only
    today's purchases and the daily summary only yesterday's gains, which is why
    the window cannot be shorter than two days.
    """
    from src.models.coin_log import CoinLog
    from src.models.shop_purchase import ShopPurchase

    days = settings.get('coin_log_retention_days') or 0
    if days <= 0:
        return 'skipped: coin history is kept indefinitely'
    days = max(days, 2)

    cutoff = datetime.utcnow() - timedelta(days=days)
    gains = (session.query(CoinLog)
             .filter(CoinLog.created_at < cutoff)
             .delete(synchronize_session=False))
    purchases = (session.query(ShopPurchase)
                 .filter(ShopPurchase.created_at < cutoff)
                 .delete(synchronize_session=False))
    return f'removed {gains} coin log entr{"y" if gains == 1 else "ies"} and {purchases} purchase record(s) older than {days} days'


@job('crate_reminder', 300,
     "Send a notification to players whose daily crate is still unclaimed at the reminder time")
def crate_reminder(session, params=None):
    """Remind everyone with notifications on whose daily crate is still waiting.

    Once a day, at `crate_reminder_time` in the primary server's timezone - the
    same clock the crate day itself runs on. The job runs every few minutes and
    does nothing until that time comes; the first run inside the window sends,
    and a Redis mark keyed to the day keeps every later run (and a second
    scheduler) from sending again.

    The mark fails *closed*, unlike the alert cooldowns: an alert that goes out
    twice is a duplicate, while a reminder that goes out every five minutes
    because Redis is down is a reason to switch notifications off for good.

    Only subscriptions whose sign-in session is still alive are sent to. Every
    run first deletes the ones whose session has expired, and the send deletes
    those whose session was ended by a password change or "sign out
    everywhere": a device nobody is signed in on stops getting reminders, and
    signing in on it again binds it afresh.
    """
    from src.models.event import Event
    from src.models.push_subscription import PushSubscription
    from src.utils import events, push
    from src.utils.redis_utils import get_redis_connection

    lapsed = (session.query(PushSubscription)
              .filter((PushSubscription.session_expires_at.is_(None))
                      | (PushSubscription.session_expires_at <= datetime.utcnow()))
              .delete(synchronize_session=False))
    if lapsed:
        logger.info(f"crate_reminder: removed {lapsed} subscription(s) whose session expired")

    at = push.parse_time(settings.get('crate_reminder_time'))
    if at is None:
        return 'skipped: the reminder time is not a valid HH:MM'

    now_local = datetime.now(daily.primary_timezone())
    if not push.reminder_due(now_local, at):
        return f'not due: reminders go out at {at:%H:%M}'
    today = now_local.date()

    event = events.system_event(session, Event.TYPE_DAILY)
    if not event or not event.enabled or not events.event_box_entries(session, event.id):
        return 'skipped: there is no daily crate to claim'

    try:
        first = get_redis_connection().set(f'push:crate-reminder:{today.isoformat()}', '1',
                                           nx=True, ex=2 * 86400)
    except Exception as e:
        return f'skipped: could not check whether today was already sent ({e})'
    if not first:
        return f'already sent for {today}'

    claimed = (session.query(UserBox.user_id)
               .filter(UserBox.source == UserBox.SOURCE_DAILY,
                       UserBox.grant_date == today))
    rows = (session.query(PushSubscription.id, PushSubscription.endpoint,
                          PushSubscription.token_version, User.token_version)
            .join(User, User.id == PushSubscription.user_id)
            .filter(User.role != User.ROLE_BANNED,
                    ~PushSubscription.user_id.in_(claimed))
            .all())
    # Made in a session that has since been ended. Deleted by id rather than
    # with a subquery, which MariaDB refuses on the table being deleted from.
    ended = [sub_id for sub_id, _, sub_tv, user_tv in rows if sub_tv != (user_tv or 0)]
    if ended:
        (session.query(PushSubscription)
         .filter(PushSubscription.id.in_(ended))
         .delete(synchronize_session=False))
    endpoints = [endpoint for _, endpoint, sub_tv, user_tv in rows if sub_tv == (user_tv or 0)]
    if not endpoints:
        return 'nobody with notifications on has an unclaimed crate'

    ttl = push.seconds_until_midnight(now_local)

    def deliver():
        # Outside the job's transaction: this waits on the game-server and on
        # the push services behind it.
        from src.database import db
        outcomes = push.send(endpoints, ttl=ttl, topic='daily-crate')
        with db.get_db() as s:
            sent, removed = push.record(s, outcomes)
        logger.info(f"crate_reminder: delivered {sent} of {len(endpoints)}, "
                    f"removed {removed} dead subscription(s)")

    return f'reminding {len(endpoints)} device(s) of an unclaimed crate', deliver


@job('settle_coins', 86400,
     'Check every linked character and pay the coins it has earned by playing')
def settle_coins(session, params=None):
    """Settle what every linked character has earned since it was last checked.

    Characters are also checked whenever their data is looked at; this is the
    sweep that reaches the ones nobody looks at. One request per server: a
    running server with players online is told to save first and the read waits
    for the save to land, so the counts are current rather than as of the last
    autosave; then every account's character comes back in one read.

    Runs even while coins are switched off, so the counters keep up and
    switching coins on later pays nothing for the time they were off. The reads
    wait on the game-server, so they run after the job's transaction, and each
    character is settled in a transaction of its own.
    """
    from src.models.character import Character
    from src.utils import coins
    from src.utils.game_server import gs_request

    by_server = {}
    for character_id, server_id, username in (
            session.query(Character.id, Character.server_id, Character.in_game_username)
            .filter(Character.verified.is_(True),
                    Character.server_id.isnot(None),
                    Character.in_game_username.isnot(None))):
        by_server.setdefault(server_id, []).append((character_id, username))
    if not by_server:
        return 'no linked characters to settle'

    def settle_all():
        read = paid = 0
        notes = []
        for server_id, linked in sorted(by_server.items()):
            payload, status = gs_request('POST', f'/api/servers/{server_id}/characters/snapshot',
                                         json={'save': True}, timeout=SNAPSHOT_TIMEOUT)
            if status != 200:
                notes.append(f"server {server_id}: {(payload or {}).get('error') or status}")
                continue
            data = payload.get('data') or {}
            if data.get('saved') is False:
                notes.append(f"server {server_id}: read the last save, a new one did not land "
                              f"({data.get('save_detail')})")
            found = {(c.get('username') or '').lower(): c for c in data.get('characters') or []}
            for character_id, username in linked:
                reading = coins.reading_from_summary(found.get(username.lower()),
                                                     data.get('saved_at'))
                if reading is None:
                    continue
                read += 1
                paid += coins.settle_quietly(character_id, reading)
        return f"read {read}, paid {paid} coin(s)" + ''.join(f'; {n}' for n in notes)

    count = sum(len(v) for v in by_server.values())
    return f'settling {count} linked character(s) on {len(by_server)} server(s)', settle_all


@job('coin_report', 3600,
     "Tell each player once a day what they earned in coins the day before")
def coin_report(session, params=None):
    """One notification per player for yesterday's coins, instead of one per payment.

    Runs every hour and does nothing until the day has turned in the primary
    server's timezone; the first run after that reports, and a Redis mark keyed
    to the day keeps every later run (and a second scheduler) from reporting
    again. The mark fails closed, as the crate reminder's does: a report that
    goes out every hour because Redis is down is worse than one that is missed.

    Staff grants are left out - each already told the player, with its reason.
    """
    from src.models.coin_log import CoinLog
    from src.utils import coins
    from src.utils.redis_utils import get_redis_connection

    if not coins.enabled():
        return 'skipped: coins are switched off'

    yesterday = daily.today() - timedelta(days=1)
    start, end = coins.day_bounds(yesterday)

    try:
        first = get_redis_connection().set(f'coins:report:{yesterday.isoformat()}', '1',
                                           nx=True, ex=3 * 86400)
    except Exception as e:
        return f'skipped: could not check whether {yesterday} was already reported ({e})'
    if not first:
        return f'already reported {yesterday}'

    rows = (session.query(CoinLog.user_id, CoinLog.source,
                          func.sum(CoinLog.amount), func.sum(CoinLog.quantity))
            .join(User, User.id == CoinLog.user_id)
            .filter(CoinLog.created_at >= start, CoinLog.created_at < end,
                    CoinLog.source != CoinLog.SOURCE_ADMIN,
                    User.role != User.ROLE_BANNED)
            .group_by(CoinLog.user_id, CoinLog.source)
            .all())
    gains = {}
    for user_id, source, amount, quantity in rows:
        gains.setdefault(user_id, []).append((source, int(amount or 0), int(quantity or 0)))

    for user_id, parts in gains.items():
        total = sum(amount for _, amount, _ in parts)
        if total <= 0:
            continue
        notify.send(session, user_id, Notification.KIND_COINS,
                    f'Yesterday you earned {total} coin{"" if total == 1 else "s"}',
                    body=coins.describe_gains(parts) + '.',
                    link='/shop')
    if not gains:
        return f'nobody earned coins on {yesterday}'
    return f'reported {yesterday} to {len(gains)} player(s)'


def describe():
    """Every registered kind, for the admin panel."""
    return [
        {'kind': kind, 'description': spec['description'],
         'default_interval': spec['default_interval']}
        for kind, spec in sorted(REGISTRY.items())
    ]

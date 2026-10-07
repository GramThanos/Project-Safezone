#!/usr/bin/env python3
"""Maintenance state: the policy, the runs, the hold and the latest checks.

Shared by the API (which reads it and takes staff decisions) and the
maintenance worker (which acts on it). The rules themselves are in
`maintenance.py`; this is where they meet the database and Redis.

Two processes write runs - an admin planning or cancelling one through the API,
and the worker moving it along - so every change to a run happens under a lock
on the single policy row. That one mutex is what keeps "is there an open run?
then make one" from creating two, and a cancel from landing between the worker
reading a run and moving it on.

The hold is *derived*: it exists exactly while a run is in a hold state, and the
worker re-asserts that on every tick. Nothing has to remember to release it - a
cancel, a failure or a finished update all release it by changing the run.
"""
import datetime
import json
import zoneinfo

import cache
import config
import database
import events
import maintenance
import models
import servers
import tasks

POLICY_ID = 1

CHECK_KEY = 'maintenance:check:'          # + 'game' / 'mods'
REQUEST_KEY = 'maintenance:check:request'
WORKER_KEY = 'maintenance:worker'
NOTIFIED_KEY = 'maintenance:notified'
# What the public server list shows players; read by the backend's
# `redis_utils.get_maintenance_notice`, so the key is shared with it.
PUBLIC_KEY = 'maintenance:public'
WORKER_TTL = 30

RUN_HISTORY = 20
LOG_LIMIT = 100


def _log(message):
    ts = datetime.datetime.now().isoformat()
    print(f"[{ts}][Maintenance] {message}")


def utcnow():
    return datetime.datetime.utcnow()


def iso(value):
    return value.isoformat() + 'Z' if value else None


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def site_timezone():
    """The primary server's timezone - the clock the schedules are read in.

    The same clock the site's daily reset follows, so "05:00" means the same
    thing on the maintenance page as everywhere else. UTC when no primary server
    has one set.
    """
    try:
        for server in servers.get_all():
            if server.get('is_primary') and server.get('timezone'):
                return zoneinfo.ZoneInfo(server['timezone'])
    except Exception as e:
        _log(f"Could not read the primary server's timezone: {e}")
    return datetime.timezone.utc


def to_local(utc_naive, tz):
    return utc_naive.replace(tzinfo=datetime.timezone.utc).astimezone(tz)


def to_utc_naive(aware):
    return aware.astimezone(datetime.timezone.utc).replace(tzinfo=None)


def next_firing(expression, tz, after_utc=None):
    """The next time a cron expression fires, as naive UTC. None if off."""
    if not str(expression or '').strip():
        return None
    try:
        spec = maintenance.parse_cron(expression)
    except ValueError:
        return None
    moment = maintenance.next_cron(spec, to_local(after_utc or utcnow(), tz))
    return to_utc_naive(moment) if moment else None


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

def _policy_row(session, lock=False):
    """The policy row, created on first use. ``lock`` makes it the run mutex."""
    query = session.query(models.MaintenancePolicy).filter(
        models.MaintenancePolicy.id == POLICY_ID)
    if lock:
        query = query.with_for_update()
    row = query.first()
    if row is None:
        row = models.MaintenancePolicy(id=POLICY_ID, settings=dict(maintenance.DEFAULT_POLICY))
        session.add(row)
        try:
            session.flush()
        except Exception:
            # Another process created it between our read and our insert.
            session.rollback()
            row = query.first()
    return row


def get_policy():
    """``(policy, meta)``: the full policy and who last changed it."""
    with database.get_context_session() as session:
        row = _policy_row(session)
        session.commit()
        return (maintenance.policy_with_defaults(row.settings),
                {'updated_by': row.updated_by, 'updated_at': iso(row.updated_at)})


def save_policy(raw, actor):
    """Validate and store a policy change. Returns ``(policy, errors)``."""
    with database.get_context_session() as session:
        row = _policy_row(session, lock=True)
        policy, errors = maintenance.validate_policy(raw, row.settings)
        if errors:
            session.rollback()
            return policy, errors
        row.settings = policy
        row.updated_by = actor
        row.updated_at = utcnow()
        session.commit()
        return policy, {}


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def read_check(kind):
    raw = cache.get_value(CHECK_KEY + kind)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def write_check(kind, record):
    # No TTL: the last answer stays the answer until there is a newer one, and
    # "unknown" after an hour would be less true than an hour-old fact.
    cache.set_value(CHECK_KEY + kind, json.dumps(record))


def request_check(kinds, actor):
    """Ask the worker for a check now. It runs there, not in the request."""
    current = {}
    raw = cache.get_value(REQUEST_KEY)
    if raw:
        try:
            current = json.loads(raw) or {}
        except (TypeError, ValueError):
            current = {}
    wanted = set(current.get('kinds') or []) | set(kinds)
    return cache.set_value(REQUEST_KEY, json.dumps({'kinds': sorted(wanted), 'by': actor}),
                           ttl=600)


def pop_check_request():
    try:
        client = cache.get_instance()
        raw = client.getdel(REQUEST_KEY) if client else None
    except Exception as e:
        _log(f"Could not read the check request: {e}")
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def note_new_updates(targets):
    """Whether these updates have not been announced to staff before.

    Remembers what was last announced, so a check every half hour that keeps
    finding the same three mods says so once rather than forty-eight times a day.
    """
    signature = {'game': (targets.get('game') or {}).get('available_build'),
                 'mods': {m['id']: m.get('updated_at') for m in targets.get('mods') or []}}
    previous = {}
    raw = cache.get_value(NOTIFIED_KEY)
    if raw:
        try:
            previous = json.loads(raw) or {}
        except (TypeError, ValueError):
            previous = {}
    cache.set_value(NOTIFIED_KEY, json.dumps(signature))
    if signature['game'] and signature['game'] != previous.get('game'):
        return True
    old_mods = previous.get('mods') or {}
    return any(old_mods.get(k) != v for k, v in signature['mods'].items())


def write_public_notice(run):
    """Tell the public server list that a restart is coming or under way.

    Only from the countdown on: a run that is merely planned may wait days for
    an empty server, and announcing that to players would be noise. Short TTL,
    refreshed every tick, so a dead worker cannot leave a stale banner up.
    """
    if run and run['status'] in ('announcing', 'stopping', 'updating'):
        cache.set_value(PUBLIC_KEY, json.dumps({
            'status': run['status'],
            'restart_at': run.get('countdown_ends_at') if run['status'] == 'announcing' else None,
        }), ttl=WORKER_TTL)
    else:
        try:
            client = cache.get_instance()
            if client:
                client.delete(PUBLIC_KEY)
        except Exception as e:
            _log(f"Could not clear the public notice: {e}")


def write_worker_status(status):
    cache.set_value(WORKER_KEY, json.dumps(status), ttl=WORKER_TTL)


def read_worker_status():
    raw = cache.get_value(WORKER_KEY)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Servers
# ---------------------------------------------------------------------------

def server_states():
    """Every server with its live state and who is on it."""
    result = []
    for server in servers.get_all():
        state = cache.get_value(f"server:{server['id']}:state")
        players = []
        raw = cache.get_value(f"server:{server['id']}:online_players")
        if raw:
            try:
                players = json.loads(raw) or []
            except (TypeError, ValueError):
                players = []
        result.append({'id': server['id'], 'name': server['name'],
                       'state': state, 'players': len(players)})
    return result


def broadcast(text):
    """Say something on every server that has a game running. Returns how many."""
    try:
        command = maintenance.broadcast_command(text)
    except Exception as e:
        _log(f"Not broadcasting an unusable message ({e}): {text}")
        return 0
    delivered = 0
    for server in servers.get_all():
        state = cache.get_value(f"server:{server['id']}:state")
        if state not in ('running', 'booting'):
            continue
        ok, detail = tasks.send_console(server, command)
        if ok:
            delivered += 1
        else:
            _log(f"Broadcast to {server['name']} failed: {detail}")
    return delivered


# ---------------------------------------------------------------------------
# Hold
# ---------------------------------------------------------------------------

def set_hold(run_id):
    cache.set_value(config.MAINTENANCE_HOLD_KEY,
                    json.dumps({'run_id': run_id, 'at': iso(utcnow())}),
                    ttl=config.MAINTENANCE_HOLD_TTL)


def release_hold():
    try:
        client = cache.get_instance()
        if client:
            client.delete(config.MAINTENANCE_HOLD_KEY)
    except Exception as e:
        _log(f"Could not release the maintenance hold: {e}")


def hold_info():
    raw = cache.get_value(config.MAINTENANCE_HOLD_KEY)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {'run_id': None}


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

def _append_log(run, text):
    entries = list(run.log or [])
    entries.append({'at': iso(utcnow()), 'text': text})
    run.log = entries[-LOG_LIMIT:]
    _log(f"Run {run.id}: {text}")


def _open_run(session):
    return (session.query(models.MaintenanceRun)
            .filter(models.MaintenanceRun.status.in_(models.MaintenanceRun.OPEN_STATES))
            .order_by(models.MaintenanceRun.id.desc())
            .first())


def open_run():
    with database.get_context_session() as session:
        run = _open_run(session)
        return run.to_dict() if run else None


def recent_runs(limit=RUN_HISTORY):
    with database.get_context_session() as session:
        rows = (session.query(models.MaintenanceRun)
                .order_by(models.MaintenanceRun.id.desc())
                .limit(limit).all())
        return [r.to_dict() for r in rows]


def _emit(event, run, **fields):
    targets = run.targets or maintenance.empty_targets()
    events.emit(event, run_id=run.id, summary=maintenance.describe_targets(targets),
                mods=[m.get('title') or m['id'] for m in targets.get('mods') or []],
                game=targets.get('game'), reason=run.reason, **fields)


def _last_suppression(session, now):
    return (session.query(models.MaintenanceRun)
            .filter(models.MaintenanceRun.status == 'cancelled',
                    models.MaintenanceRun.suppress_until > now)
            .order_by(models.MaintenanceRun.id.desc())
            .first())


def plan(targets, trigger, actor=None, now_mode=False, policy=None, automatic=False):
    """Plan a run for ``targets``, or fold them into the one already waiting.

    ``now_mode`` is staff saying "do it now": the countdown starts on the
    worker's next tick instead of waiting for an empty server or the window.
    ``automatic`` marks the worker planning on its own, which is the only
    planning a recent cancel holds back - staff planning by hand is the
    override. Returns ``(run_dict, error)``.
    """
    if not maintenance.has_targets(targets):
        return None, 'Nothing to update'
    policy = policy or get_policy()[0]
    now = utcnow()
    with database.get_context_session() as session:
        _policy_row(session, lock=True)
        run = _open_run(session)
        if run and run.status not in ('scheduled', 'announcing'):
            session.rollback()
            return None, ('A maintenance run is already taking the servers down; '
                          'plan this once it has finished.')

        if automatic and not run:
            cancelled = _last_suppression(session, now)
            if cancelled and maintenance.covered_by(cancelled.targets, targets):
                session.rollback()
                return None, 'suppressed: staff cancelled these updates recently'

        if run:
            before = maintenance.describe_targets(run.targets)
            run.targets = maintenance.merge_targets(run.targets, targets)
            after = maintenance.describe_targets(run.targets)
            if after != before:
                _append_log(run, f"Now covers {after}" + (f" (added by {actor})" if actor else ''))
            if now_mode and run.status == 'scheduled' and not run.force_at:
                run.force_at = now
                _append_log(run, f"{actor or 'Staff'} asked for it to go now")
            run.updated_at = now
            session.commit()
            return run.to_dict(), None

        hours = policy.get('max_wait_hours') or 0
        run = models.MaintenanceRun(
            status='scheduled', trigger=trigger, requested_by=actor,
            targets=maintenance.merge_targets(None, targets),
            force_at=now if now_mode else None,
            deadline=now + datetime.timedelta(hours=hours) if hours else None,
            announced=[], log=[], task_ids=[],
            created_at=now, updated_at=now,
        )
        session.add(run)
        session.flush()
        _append_log(run, f"Planned {maintenance.describe_targets(run.targets)}"
                         + (f" by {actor}" if actor else f" ({trigger} check)")
                         + ('; going now' if now_mode else ''))
        session.commit()
        _emit('maintenance.scheduled', run, actor=actor, immediate=bool(now_mode))
        return run.to_dict(), None


def transition(run_id, expected, status, reason=None, note=None, **changes):
    """Move a run on, if it is still where the caller thinks it is.

    Returns the updated run dict, or None when somebody else moved it first
    (staff cancelled it between the worker reading it and acting).
    """
    now = utcnow()
    with database.get_context_session() as session:
        _policy_row(session, lock=True)
        run = session.query(models.MaintenanceRun).filter(
            models.MaintenanceRun.id == run_id).first()
        if not run or run.status not in (expected if isinstance(expected, tuple) else (expected,)):
            session.rollback()
            return None
        run.status = status
        if reason:
            run.reason = reason
        for key, value in changes.items():
            setattr(run, key, value)
        if status in ('completed', 'failed', 'cancelled'):
            run.finished_at = now
        run.updated_at = now
        if note:
            _append_log(run, note)
        session.commit()
        return run.to_dict()


def update_run(run_id, note=None, **changes):
    with database.get_context_session() as session:
        run = session.query(models.MaintenanceRun).filter(
            models.MaintenanceRun.id == run_id).first()
        if not run:
            return None
        for key, value in changes.items():
            setattr(run, key, value)
        if note:
            _append_log(run, note)
        run.updated_at = utcnow()
        session.commit()
        return run.to_dict()


def emit(event, run_id, **fields):
    with database.get_context_session() as session:
        run = session.query(models.MaintenanceRun).filter(
            models.MaintenanceRun.id == run_id).first()
        if run:
            _emit(event, run, **fields)


def cancel(run_id, actor):
    """Call off a run before it touches any files. Returns ``(run, error)``.

    Releases the servers straight away, tells the players if they were warned,
    and keeps the same updates from being planned again on their own until the
    next maintenance window - otherwise the maximum wait would reschedule them
    on the worker's next tick and the cancel would mean nothing.
    """
    policy = get_policy()[0]
    tz = site_timezone()
    now = utcnow()
    suppress_until = next_firing(policy.get('window_cron'), tz, now)
    if suppress_until is None:
        suppress_until = now + datetime.timedelta(hours=policy.get('max_wait_hours') or 24)

    with database.get_context_session() as session:
        _policy_row(session, lock=True)
        run = session.query(models.MaintenanceRun).filter(
            models.MaintenanceRun.id == run_id).first()
        if not run:
            session.rollback()
            return None, 'No such maintenance run'
        if run.status not in models.MaintenanceRun.CANCELLABLE_STATES:
            session.rollback()
            if run.status == 'updating':
                return None, ('The update is already running and cannot be stopped '
                              'halfway; the servers come back when it finishes.')
            return None, f'This run is already {run.status}'
        warned = run.status in ('announcing', 'stopping') and bool(run.announced)
        was_holding = run.status in models.MaintenanceRun.HOLD_STATES
        run.status = 'cancelled'
        run.cancelled_by = actor
        run.reason = f'cancelled by {actor}' if actor else 'cancelled'
        run.finished_at = now
        run.updated_at = now
        run.suppress_until = suppress_until
        _append_log(run, f"Cancelled by {actor or 'staff'}; not planned again "
                         f"automatically before {iso(suppress_until)}")
        session.commit()
        result = run.to_dict()
        _emit('maintenance.cancelled', run, actor=actor)

    if was_holding:
        release_hold()
    if warned and policy.get('cancel_message'):
        broadcast(policy['cancel_message'])
    return result, None


def go_now(run_id, actor):
    """Stop waiting for an empty server or the window: start the countdown."""
    now = utcnow()
    with database.get_context_session() as session:
        _policy_row(session, lock=True)
        run = session.query(models.MaintenanceRun).filter(
            models.MaintenanceRun.id == run_id).first()
        if not run:
            session.rollback()
            return None, 'No such maintenance run'
        if run.status != 'scheduled':
            session.rollback()
            return None, f'This run is already {run.status}'
        if run.force_at:
            # Asked twice (two admins, or a double click): already going.
            session.rollback()
            return run.to_dict(), None
        run.force_at = now
        run.updated_at = now
        _append_log(run, f"{actor or 'Staff'} asked for it to go now")
        session.commit()
        return run.to_dict(), None


def overview():
    """Everything the maintenance page shows, in one read."""
    policy, meta = get_policy()
    return {
        'policy': policy,
        'policy_meta': meta,
        'defaults': maintenance.DEFAULT_POLICY,
        'open_run': open_run(),
        'runs': recent_runs(),
        'checks': {'game': read_check('game'), 'mods': read_check('mods')},
        'hold': hold_info(),
        'worker': read_worker_status(),
        'servers': server_states(),
        'check_requested': bool(cache.get_value(REQUEST_KEY)),
    }

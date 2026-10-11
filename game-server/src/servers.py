#!/usr/bin/env python3
import time
import random
import string
import datetime
import threading

# Custom modules
import database
import models
import mods
import server_config


# Logging

def _log(message):
    ts = datetime.datetime.now().isoformat()
    print(f"[{ts}][Servers] {message}")


# Servers

def get_all(limit=None, offset=0):
    """List all server with optional filtering"""
    with database.get_context_session() as session:
        query = session.query(models.Server)
        
        query = query.order_by(models.Server.name.desc())
        
        if limit:
            query = query.limit(limit).offset(offset)
        
        servers = query.all()
        return [server.to_dict() for server in servers]

def mod_usage():
    """Which servers reference which Workshop item, and which mod names.

    Read from each server's own INI rather than from a table, because the INI is
    what the game reads - a cached copy would be one more thing to drift.
    Returns ``(items, names)``, both mapping value -> sorted server names.
    """
    items = {}
    names = {}
    for server in get_all():
        settings, error = server_config.read(server['name'])
        if error:
            # A server whose config cannot be read yet (never started) simply
            # uses nothing; it is not a reason to fail the whole listing.
            continue
        values = {s['key']: s.get('value') for s in settings}
        for item_id in mods.parse_list(values.get('WorkshopItems')):
            items.setdefault(item_id, set()).add(server['name'])
        for name in mods.parse_list(values.get('Mods')):
            names.setdefault(name, set()).add(server['name'])
    return ({k: sorted(v) for k, v in items.items()},
            {k: sorted(v) for k, v in names.items()})


def _clear_primary(session, except_id=None):
    """Demote every other server, so "primary" stays a single answer."""
    query = session.query(models.Server).filter(models.Server.is_primary.is_(True))
    if except_id is not None:
        query = query.filter(models.Server.id != except_id)
    query.update({'is_primary': False}, synchronize_session=False)


def update(server_id, data=None):
    """Update server data with safe JSON parsing"""
    if not data:
        return False, "No data provided"
    
    with database.get_context_session() as session:
        server = session.query(models.Server).filter(models.Server.id == server_id).first()
        if not server:
            return False, "Server not found"
        
        if 'name' in data:
            server.name = data['name']
        if 'hostname' in data:
            server.hostname = data['hostname']
        if 'description' in data:
            server.description = data['description']
        if 'ports' in data:
            server.ports = data['ports']
        if 'default_state' in data:
            server.default_state = data['default_state']
        if 'idle_sleep_seconds' in data:
            server.idle_sleep_seconds = data['idle_sleep_seconds']
        if 'timezone' in data:
            server.timezone = data['timezone']
        if 'is_primary' in data:
            if data['is_primary']:
                _clear_primary(session, except_id=server.id)
                server.is_primary = True
            else:
                server.is_primary = False

        session.commit()
        return True, server.to_dict()

def create(data=None):
    """Create a new server"""
    if not data or 'name' not in data:
        return False

    with database.get_context_session() as session:
        server = models.Server(
            name=data.get('name', 'zomboid_server' + ''.join(random.choices(string.ascii_lowercase + string.digits, k=5))),
            hostname=data.get('hostname'),
            description=data.get('description'),
            ports=data.get('ports', [16261, 16262]),
            default_state=data.get('default_state', 'stopped'),
            idle_sleep_seconds=data.get('idle_sleep_seconds', 0),
            timezone=data.get('timezone'),
            is_primary=bool(data.get('is_primary'))
        )
        if server.is_primary:
            _clear_primary(session)
        session.add(server)
        session.commit()
        session.refresh(server)
        return server.to_dict()

def get(server_id):
    """Get specific server by ID"""
    with database.get_context_session() as session:
        server = session.query(models.Server).filter(models.Server.id == server_id).first()
        return server.to_dict() if server else None

def delete(server_id):
    """Delete a server"""
    with database.get_context_session() as session:
        server = session.query(models.Server).filter(models.Server.id == server_id).first()

        if not server:
            return False, "Server not found"

        # Drop the server's history too, so counts don't outlive the server.
        session.query(models.ServerPlayerCount).filter(
            models.ServerPlayerCount.server_id == server_id
        ).delete(synchronize_session=False)

        session.delete(server)
        session.commit()
        return True, None


# Player-count history

PLAYER_COUNT_RETENTION_DAYS = 7
_PRUNE_INTERVAL_SECONDS = 3600

_prune_lock = threading.Lock()
_last_prune = None


def _maybe_prune_player_counts():
    """Prune old samples at most once an hour.

    There is no periodic scheduler in this service, so pruning piggybacks on the
    roster workers that write the samples. The lock keeps the several server
    manager threads from all pruning at once.
    """
    global _last_prune
    now = time.monotonic()
    with _prune_lock:
        if _last_prune is not None and now - _last_prune < _PRUNE_INTERVAL_SECONDS:
            return
        _last_prune = now
    removed = prune_player_counts(days=PLAYER_COUNT_RETENTION_DAYS)
    if removed:
        _log(f"Pruned {removed} player-count samples older than {PLAYER_COUNT_RETENTION_DAYS} days")


def record_player_count(server_id, count):
    """Append an online-player-count sample for a server.

    Called by the roster worker each poll. Failures are logged but never raised:
    losing a sample must not disrupt server management.
    """
    try:
        with database.get_context_session() as session:
            session.add(models.ServerPlayerCount(server_id=server_id, count=int(count)))
            session.commit()
    except Exception as e:
        _log(f"Failed to record player count for server {server_id}: {e}")
        return False

    _maybe_prune_player_counts()
    return True


def get_player_history(server_id, hours=24, bucket_minutes=15):
    """Return the online-player history for a server as time buckets.

    Every bucket in the window is returned, oldest first, as
    ``{'t': iso_timestamp_utc, 'count': int}`` - so the chart spans the whole
    window at true spacing. A bucket with no samples is 0: samples are only
    written while the game is running, so a stopped or sleeping server has
    nobody on it. A bucket's count is the peak seen in it rather than the
    average, so a player on for five minutes still shows.

    ``created_at`` is naive, in the database's clock, which compose sets to
    the same ``TZ`` as this container; ``timestamp()`` reads it in that zone.
    The output carries an explicit UTC offset so the browser can show it in
    the viewer's own zone.
    """
    hours = max(1, min(int(hours), 24 * 7))
    bucket_minutes = max(1, int(bucket_minutes))
    now = datetime.datetime.now()
    since = now - datetime.timedelta(hours=hours)

    with database.get_context_session() as session:
        rows = session.query(
            models.ServerPlayerCount.count,
            models.ServerPlayerCount.created_at
        ).filter(
            models.ServerPlayerCount.server_id == server_id,
            models.ServerPlayerCount.created_at >= since
        ).order_by(models.ServerPlayerCount.created_at.asc()).all()

    return bucket_player_counts(rows, since, now, bucket_minutes)


def bucket_player_counts(rows, since, now, bucket_minutes):
    """Snap ``(count, created_at)`` samples into every bucket from ``since``
    to ``now`` (naive, local), taking each bucket's peak; empty ones are 0."""
    bucket_seconds = bucket_minutes * 60

    def bucket_of(moment):
        epoch = int(moment.timestamp())
        return epoch - (epoch % bucket_seconds)

    peaks = {}
    for count, created_at in rows:
        if not created_at:
            continue
        start = bucket_of(created_at)
        peaks[start] = max(peaks.get(start, 0), count or 0)

    first, last = bucket_of(since), bucket_of(now)
    return [
        {
            't': datetime.datetime.fromtimestamp(start, tz=datetime.timezone.utc).isoformat(),
            'count': peaks.get(start, 0)
        }
        for start in range(first, last + bucket_seconds, bucket_seconds)
    ]


def prune_player_counts(days=7):
    """Delete player-count samples older than ``days``. Returns rows removed."""
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    try:
        with database.get_context_session() as session:
            removed = session.query(models.ServerPlayerCount).filter(
                models.ServerPlayerCount.created_at < cutoff
            ).delete(synchronize_session=False)
            session.commit()
            return removed
    except Exception as e:
        _log(f"Failed to prune player counts: {e}")
        return 0

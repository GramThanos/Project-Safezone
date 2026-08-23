"""Redis connection utilities"""
import json
import logging
import redis

logger = logging.getLogger(__name__)

# Redis connection pool for better performance
_redis_pool = None


def init_redis_pool(app):
    """Initialize Redis connection pool with app configuration"""
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.ConnectionPool(
            host=app.config['REDIS_HOST'],
            port=app.config['REDIS_PORT'],
            decode_responses=True,
            max_connections=10
        )
        logger.info("Redis connection pool initialized")


def get_redis_connection():
    """Get Redis connection from pool"""
    try:
        if _redis_pool is None:
            logger.error("Redis pool not initialized. Call init_redis_pool first.")
            return None
        return redis.Redis(connection_pool=_redis_pool)
    except Exception as e:
        logger.error(f"Redis connection error: {e}")
        return None


def cache_get(key):
    """Return a cached JSON value for ``key``, or None on miss/error.

    Best-effort: a cache that is down must never be more than a slow path, so
    every failure reads as a miss and the caller recomputes.
    """
    r = get_redis_connection()
    if not r:
        return None
    try:
        raw = r.get(key)
        return json.loads(raw) if raw else None
    except Exception as e:
        logger.error(f"Cache read error for {key}: {e}")
        return None


def cache_set(key, value, ttl_seconds):
    """Store ``value`` as JSON under ``key`` with a TTL. Never raises.

    A write failure just means the next read is another miss, so it is logged
    and swallowed rather than allowed to fail the request that produced the
    value.
    """
    r = get_redis_connection()
    if not r:
        return
    try:
        r.setex(key, ttl_seconds, json.dumps(value))
    except Exception as e:
        logger.error(f"Cache write error for {key}: {e}")


def apply_live_state(servers):
    """Overlay the live runtime state published by the game-server orchestrator.

    The orchestrator writes the actual state (running/sleeping/stopped) to the
    Redis key ``server:<id>:state``. When present it is exposed as ``state`` and
    overrides the configured ``default_state``; otherwise ``state`` falls back to
    ``default_state``. Mutates and returns the given list of server dicts.
    """
    r = get_redis_connection()
    for server in servers:
        live_state = None
        if r:
            try:
                live_state = r.get(f"server:{server['id']}:state")
            except Exception as e:
                logger.error(f"Redis live-state read error for server {server.get('id')}: {e}")
        server['state'] = live_state or server.get('default_state')
    return servers


def get_online_players(server_id):
    """Return the set of in-game usernames currently online on a server.

    Reads the roster published by the game-server orchestrator. Returns an empty
    set on miss or error.
    """
    r = get_redis_connection()
    if not r:
        return set()
    try:
        raw = r.get(f"server:{server_id}:online_players")
        if not raw:
            return set()
        data = json.loads(raw)
        return set(data) if isinstance(data, list) else set()
    except Exception as e:
        logger.error(f"Online players read error for server {server_id}: {e}")
        return set()


def is_player_online(server_id, username):
    """Whether a given in-game username is currently online on a server."""
    return username in get_online_players(server_id)

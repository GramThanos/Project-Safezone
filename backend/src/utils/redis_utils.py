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

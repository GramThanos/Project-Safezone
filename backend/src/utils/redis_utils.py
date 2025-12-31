"""Redis connection utilities"""
import logging
import redis
from flask import current_app

logger = logging.getLogger(__name__)

# Redis connection pool for better performance
_redis_pool = None


def get_redis_connection():
    """Get Redis connection from pool"""
    global _redis_pool
    try:
        if _redis_pool is None:
            _redis_pool = redis.ConnectionPool(
                host=current_app.config['REDIS_HOST'],
                port=current_app.config['REDIS_PORT'],
                decode_responses=True,
                max_connections=10
            )
        return redis.Redis(connection_pool=_redis_pool)
    except Exception as e:
        logger.error(f"Redis connection error: {e}")
        return None

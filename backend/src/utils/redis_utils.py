"""Redis connection utilities"""
import os
import logging
import redis

logger = logging.getLogger(__name__)

# Redis connection pool for better performance
_redis_pool = None


def get_redis_connection():
    """Get Redis connection from pool"""
    global _redis_pool
    try:
        if _redis_pool is None:
            _redis_pool = redis.ConnectionPool(
                host=os.getenv('REDIS_HOST', 'cache'),
                port=int(os.getenv('REDIS_PORT', '6379')),
                decode_responses=True,
                max_connections=10
            )
        return redis.Redis(connection_pool=_redis_pool)
    except Exception as e:
        logger.error(f"Redis connection error: {e}")
        return None

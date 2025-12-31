"""Redis connection utilities"""
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

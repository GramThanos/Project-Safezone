"""
Redis cache operations module
Handles all Redis connections and operations
"""
import redis
from config import REDIS_HOST, REDIS_PORT, REDIS_CHANNEL


def get_redis_connection():
    """Get Redis connection and validate it's working"""
    try:
        r = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True
        )
        # Validate connection is working
        r.ping()
        return r
    except Exception as e:
        print(f"Redis connection error: {e}")
        return None


def notify_new_task():
    """Notify task processor about new task via Redis pub/sub"""
    try:
        r = get_redis_connection()
        if r:
            r.publish(REDIS_CHANNEL, 'new_task')
            return True
        else:
            print("Warning: Redis unavailable, cannot send task notification")
    except Exception as e:
        print(f"Error notifying new task: {e}")
    return False


def subscribe_to_channel():
    """Subscribe to task notifications channel"""
    r = get_redis_connection()
    if not r:
        return None
    
    try:
        pubsub = r.pubsub()
        pubsub.subscribe(REDIS_CHANNEL)
        
        # Test subscription is working
        test_message = pubsub.get_message(timeout=0.1)
        print(f"Redis pub/sub subscription successful on channel '{REDIS_CHANNEL}'")
        return pubsub
    except Exception as e:
        print(f"ERROR: Failed to setup Redis pub/sub: {e}")
        return None

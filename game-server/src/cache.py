#!/usr/bin/env python3
import json
import redis
import datetime
import time

# Custom modules
import config

# Global pool configuration
_REDIS_POOL = redis.ConnectionPool.from_url(
    config.CACHE_URL,
    decode_responses=True,
    max_connections=config.CACHE_MAX_CONNECTIONS,
    health_check_interval=config.CACHE_HEALTH_CHECK_INTERVAL
)

def _log(message):
    ts = datetime.datetime.now().isoformat()
    print(f"[{ts}][Redis Cache] {message}")

def wait(timeout=30):
    """Wait for Cache to become available"""
    _log(f"Checking cache availability...")
    start_time = datetime.datetime.now()
    while True:
        try:
            r = redis.Redis(connection_pool=_REDIS_POOL)
            r.ping()
            _log("Cache is available")
            return True
        except Exception as e:
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            if elapsed > timeout:
                _log(f"Timeout reached while waiting for Cache: {e}")
                return False
            #_log(f"Waiting for Cache... ({e})")
            time.sleep(2)

def get_instance():
    """Get a client from the pool. This is fast and thread-safe."""
    try:
        return redis.Redis(connection_pool=_REDIS_POOL)
    except Exception as e:
        _log(f"ERROR: Failed to connect to Redis: {e}")
        return None

def set_value(key, value, ttl=None):
    """Set a key in the cache, optionally with a TTL (seconds)."""
    try:
        r = get_instance()
        if r:
            r.set(key, value, ex=ttl)
            return True
    except Exception as e:
        _log(f"ERROR: set_value failed for {key}: {e}")
    return False

def get_value(key):
    """Get a key from the cache, or None on miss/error."""
    try:
        r = get_instance()
        if r:
            return r.get(key)
    except Exception as e:
        _log(f"ERROR: get_value failed for {key}: {e}")
    return None

def broadcast_to_channel(channel, message):
    """Short-lived connection: Use pool to avoid 3-way handshake overhead."""
    try:
        
        message = message if isinstance(message, str) else (json.dumps(message) if isinstance(message, (dict, list)) else str(message))
        r = get_instance()
        if r:
            r.publish(channel, message)
            return True
    except Exception as e:
        _log(f"ERROR: Broadcast failed: {e}")
    return False

def subscribe_to_channel(channel):
    """
    Long-lived connection: The pool provides a dedicated socket 
    for this PubSub object.
    """
    r = get_instance()
    if not r: return None
    
    try:
        pubsub = r.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(channel)
        #_log(f"Subscribed to {channel}")
        return pubsub
    except Exception as e:
        #_log(f"ERROR: Subscription failed: {e}")
        return None

def listen_to_channel(pubsub_instance):
    """
    Generator to consume events.
    The finally block ensures the connection returns to the pool 
    when the dynamic thread exits.
    """
    if not pubsub_instance:
        return

    try:
        # This loop blocks and waits for events (Long-lived)
        for message in pubsub_instance.listen():
            if message['type'] == 'message':
                yield message['data']
    except redis.ConnectionError:
        _log("NOTICE: Redis connection lost while listening.")
    except Exception as e:
        _log(f"ERROR: Listener exception: {e}")
    finally:
        # CRITICAL: Returns the connection to the pool so it's not leaked
        pubsub_instance.close()
        _log("PubSub connection closed and returned to pool.")

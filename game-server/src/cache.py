#!/usr/bin/env python3
# Redis cache module

import redis
from config import CACHE_HOST, CACHE_PORT

def get_instance():
    """Get Redis connection"""
    try:
        r = redis.Redis(
            host=CACHE_HOST,
            port=CACHE_PORT,
            decode_responses=True
        )
        # Validate connection is working
        r.ping()
        return r
    except Exception as e:
        print(f"[CACHE] ERROR: Failed to connect to Redis: {e}")
        return None


def broadcast_to_channel(channel, message):
    """Broaccase a message to channel"""
    try:
        r = get_instance()
        if r:
            r.publish(channel, message)
            return True
        else:
            raise("Redis not available")
    except Exception as e:
        print(f"[CACHE] ERROR: Failed to broadcast to channel: {e}")
    return False


def subscribe_to_channel(channel):
    """Subscribe to channel"""
    r = get_instance()
    if not r:
        return None
    
    try:
        pubsub = r.pubsub()
        pubsub.subscribe(channel)
        return pubsub
    except Exception as e:
        print(f"[CACHE] ERROR: Failed to setup Redis pub/sub: {e}")
        return None

def listen_to_channel(channel):
    """Liste to channel"""
    return channel.listen()

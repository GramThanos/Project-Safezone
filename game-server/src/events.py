#!/usr/bin/env python3
"""Things the manager saw, left where the backend can find them.

A player joining and a server giving up are only visible from in here, but the
list of who wants to hear about them lives in the backend's database - and the
manager does not call the backend. That dependency runs one way through the
whole stack and inverting it for a notification would be a poor trade.

So this is a queue: the manager pushes what happened, the backend's scheduler
drains it and decides who to tell. Newest at the head and trimmed to a cap, so a
backend that was down for an hour comes back to the recent past rather than an
hour of stale "so-and-so joined".

Never raises. Nothing in the game loop should stop because Redis is unhappy.
"""
import datetime
import json

import cache
import config


def _log(message):
    ts = datetime.datetime.now().isoformat()
    print(f"[{ts}][Events] {message}")


def emit(event, **fields):
    """Queue one event for the backend. Returns True when it was stored."""
    entry = {
        'event': event,
        'ts': datetime.datetime.utcnow().isoformat() + 'Z',
        **fields
    }
    try:
        client = cache.get_instance()
        if not client:
            return False
        pipe = client.pipeline()
        pipe.lpush(config.WEBHOOK_EVENT_QUEUE, json.dumps(entry))
        pipe.ltrim(config.WEBHOOK_EVENT_QUEUE, 0, config.WEBHOOK_EVENT_QUEUE_MAX - 1)
        # Expire the whole queue if nothing drains it, so a deployment with no
        # webhooks configured does not keep a capped list alive in Redis
        # forever. Refreshed on every push, so a live queue never expires.
        pipe.expire(config.WEBHOOK_EVENT_QUEUE, config.WEBHOOK_EVENT_QUEUE_TTL)
        pipe.execute()
        return True
    except Exception as e:
        _log(f"ERROR: could not queue event {event}: {e}")
        return False

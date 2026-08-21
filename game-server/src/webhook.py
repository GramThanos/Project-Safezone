#!/usr/bin/env python3
"""Relaying an alert to a Discord webhook.

The backend decides what to say and who to say it to; it cannot say it. It sits
on the compose `internal` network, which has no egress and no DNS, and that is
deliberate - the service holding authentication and untrusted user input is not
the service that should be able to reach the internet. This container can, so
the message comes here to be posted.

**That makes this module a hole in the egress boundary, and the allowlist is
what keeps it a small one.** A relay that posts anywhere is a server-side
request forgery primitive with an admin-editable target: whoever can add a
webhook in the panel could aim it at an internal address and read the response.
So the URL has to be an HTTPS Discord webhook endpoint, checked here rather than
only in the panel, and nothing of the response body comes back - only the status
code, which is what tells a deleted webhook from a rate limit.

stdlib `urllib` on purpose: `requests` is not a dependency of this container and
one JSON POST is not a reason to make it one.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

import config

# Discord's own hosts. `discordapp.com` is the old domain and still works, so
# webhooks copied out of an old wiki page keep working; the ptb/canary hosts are
# what the beta clients hand out.
ALLOWED_HOSTS = {
    'discord.com',
    'discordapp.com',
    'ptb.discord.com',
    'canary.discord.com',
}
WEBHOOK_PATH_PREFIX = '/api/webhooks/'


def is_webhook_url(url):
    """Whether this is a Discord webhook endpoint we are willing to post to."""
    if not url or not isinstance(url, str) or len(url) > 512:
        return False
    try:
        parts = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return False
    if parts.scheme != 'https':
        return False
    # `hostname` rather than `netloc`: it drops any `user:pass@` and the port,
    # both of which are ways to make a netloc read as one host and resolve as
    # another.
    if (parts.hostname or '').lower() not in ALLOWED_HOSTS:
        return False
    if parts.port not in (None, 443):
        return False
    return parts.path.startswith(WEBHOOK_PATH_PREFIX)


def post(url, payload):
    """POST one message. Returns ``(ok, status, error)``.

    ``status`` is Discord's HTTP status when it answered at all, and ``None``
    when the request never got that far. Never raises.
    """
    if not is_webhook_url(url):
        return False, None, 'Not a Discord webhook URL'

    try:
        body = json.dumps(payload).encode('utf-8')
    except (TypeError, ValueError) as e:
        return False, None, f'Unserialisable payload: {e}'

    request = urllib.request.Request(
        url,
        data=body,
        headers={
            'Content-Type': 'application/json',
            'User-Agent': 'ProjectSafezone (webhook relay)',
        },
        method='POST'
    )

    try:
        with urllib.request.urlopen(request, timeout=config.WEBHOOK_TIMEOUT) as response:
            # Discord answers 204 No Content on success.
            return (200 <= response.status < 300), response.status, None
    except urllib.error.HTTPError as e:
        # 429 is a rate limit and 404 means the webhook was deleted in Discord;
        # the caller decides what to do with each, so the code is passed back
        # rather than flattened into "it failed".
        return False, e.code, f'Discord returned {e.code}'
    except urllib.error.URLError as e:
        return False, None, f'Could not reach Discord: {e.reason}'
    except Exception as e:
        return False, None, f'Webhook relay failed: {e}'

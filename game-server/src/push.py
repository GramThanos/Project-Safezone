#!/usr/bin/env python3
"""Sending Web Push notifications on the backend's behalf.

Same reason as the Discord and mail relays: the backend has no egress, so the
backend decides who to remind and this container puts the requests on the wire.

**Payloadless on purpose.** A push with no body needs no message encryption
(RFC 8291) - only the VAPID signature that proves it came from us (RFC 8292) -
so one `cryptography` dependency covers it. The text the player sees lives in
the browser's service worker (`frontend/public/sw.js`), which is why every push
sent today means "your daily crate is waiting". Varying the text per push would
mean adding the payload encryption here.

**The endpoint comes from a player's browser**, which makes it the least
trusted URL any relay here handles: a player can submit anything. Without the
allowlist, `POST /api/push` would aim an HTTPS request from this container -
which sits on the internal network - at an address of the player's choosing.
So it only ever talks to the browser vendors' own push services, checked here at
send time, and nothing of a response comes back except the status.

**Grouping.** Web Push has no batch call: every device is its own POST. What
can be shared is shared. The backend sends the whole list in one call; the
VAPID token is signed once per push service rather than once per device; and
each push service gets a few kept-alive HTTPS connections that its devices are
sent down in turn, so a thousand reminders cost a handful of TLS handshakes.

stdlib `http.client` rather than `urllib`, because `urllib` cannot keep a
connection alive between requests.
"""
import base64
import datetime
import http.client
import json
import os
import re
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

import config

# The browsers' push services: Chrome, Android, Opera and Samsung Internet use
# Google's; Firefox uses Mozilla's; Safari uses Apple's; Edge uses Windows
# Notification Services, whose hosts are regional (wns2-par02p.notify.windows.com).
ALLOWED_HOSTS = {
    'fcm.googleapis.com',
    'updates.push.services.mozilla.com',
}
ALLOWED_SUFFIXES = (
    '.push.apple.com',
    '.notify.windows.com',
)

# RFC 8292 caps a VAPID token at 24 hours; half that leaves room for clock skew.
TOKEN_LIFETIME = 12 * 3600
# RFC 8030 has no upper bound on TTL; services cap it at about four weeks.
MAX_TTL = 28 * 86400
# The Topic header: at most 32 characters of the URL-safe base64 alphabet.
TOPIC_RE = re.compile(r'^[A-Za-z0-9_-]{1,32}$')

_key = None
_key_lock = threading.Lock()


def _log(message):
    ts = datetime.datetime.now().isoformat()
    print(f"[{ts}][Push] {message}")


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def is_push_endpoint(url):
    """Whether this is a browser push service endpoint we are willing to POST to."""
    if not url or not isinstance(url, str) or len(url) > 1024:
        return False
    try:
        parts = urllib.parse.urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return False
    if parts.scheme != 'https' or port not in (None, 443):
        return False
    # Refused outright rather than stripped: `user@host` is a way of making a
    # URL read as one host and go to another.
    if parts.username is not None or parts.password is not None:
        return False
    host = (parts.hostname or '').lower()
    if host in ALLOWED_HOSTS:
        return True
    return any(host.endswith(suffix) and len(host) > len(suffix) for suffix in ALLOWED_SUFFIXES)


def _private_key():
    """The VAPID signing key: loaded from disk, or created there on first use.

    It has to survive a restart. Every browser subscribed against its public
    half, and a new key would quietly invalidate all of them.
    """
    global _key
    with _key_lock:
        if _key is not None:
            return _key
        path = config.PUSH_VAPID_KEY_FILE
        try:
            with open(path, 'rb') as f:
                _key = serialization.load_pem_private_key(f.read(), password=None)
            return _key
        except FileNotFoundError:
            pass

        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(serialization.Encoding.PEM,
                                serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        # Created exclusively and owner-readable: it is a signing key.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(pem)
        _log(f"Created a new VAPID key at {path}")
        _key = key
        return _key


def public_key():
    """The public half, as browsers want it for `applicationServerKey`."""
    point = _private_key().public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return _b64(point)


def subject_or_default(subject):
    """The VAPID contact: the caller's if usable, else this container's.

    Push services want a way to reach whoever is sending, as a `mailto:` or an
    `https:` URL, and Apple refuses a token without one.
    """
    if isinstance(subject, str) and subject.startswith(('mailto:', 'https://')) and len(subject) <= 255:
        return subject
    return config.PUSH_SUBJECT


def vapid_token(audience, subject, now=None):
    """A signed VAPID JWT for one push service (ES256)."""
    now = int(now if now is not None else time.time())
    header = _b64(json.dumps({'typ': 'JWT', 'alg': 'ES256'}, separators=(',', ':')).encode())
    claims = _b64(json.dumps({'aud': audience, 'exp': now + TOKEN_LIFETIME, 'sub': subject},
                             separators=(',', ':')).encode())
    signing_input = f'{header}.{claims}'.encode('ascii')
    der = _private_key().sign(signing_input, ec.ECDSA(hashes.SHA256()))
    # JWS wants the raw 64-byte r||s, not the DER that `sign` produces.
    r, s = decode_dss_signature(der)
    return f'{header}.{claims}.{_b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))}'


def _outcome(status):
    """What a push service's status means for the subscription."""
    if 200 <= status < 300:
        return 'ok'
    # The browser unsubscribed, the app was uninstalled or permission revoked:
    # the subscription is dead and will never work again.
    if status in (404, 410):
        return 'gone'
    # Anything else - a rate limit, an outage, a token the service did not
    # like - might be our fault or temporary, so the subscription is kept.
    return 'failed'


def _send_lane(host, headers, items):
    """Send one share of a push service's devices down a single connection."""
    out = []
    conn = None
    for index, path in items:
        result, status = 'failed', None
        # A kept-alive connection the service has since closed fails on first
        # use; one fresh connection is worth trying before calling it failed.
        for _attempt in range(2):
            try:
                if conn is None:
                    conn = http.client.HTTPSConnection(host, 443, timeout=config.PUSH_TIMEOUT)
                conn.request('POST', path, body=b'', headers=headers)
                response = conn.getresponse()
                response.read()  # drained, so the connection can carry the next one
                status = response.status
                result = _outcome(status)
                if response.will_close:
                    conn.close()
                    conn = None
                break
            except (http.client.HTTPException, OSError):
                if conn is not None:
                    conn.close()
                    conn = None
        out.append((index, result, status))
    if conn is not None:
        conn.close()
    return out


def send_many(endpoints, ttl=86400, topic=None, urgency='normal', subject=None):
    """Push to every endpoint. Returns ``[{'result', 'status'}]`` in the same order.

    ``result`` is ``ok``, ``gone`` (the subscription is dead - delete it),
    ``invalid`` (not a push service we send to - delete it), or ``failed``
    (try again another day). Never raises for a single device.
    """
    results = [{'result': 'invalid', 'status': None} for _ in endpoints]

    by_host = {}
    for index, url in enumerate(endpoints):
        if not is_push_endpoint(url):
            continue
        parts = urllib.parse.urlsplit(url.strip())
        path = (parts.path or '/') + (f'?{parts.query}' if parts.query else '')
        by_host.setdefault(parts.hostname.lower(), []).append((index, path))
    if not by_host:
        return results

    ttl = max(0, min(int(ttl), MAX_TTL))
    subject = subject_or_default(subject)
    key = public_key()

    lanes = []
    for host, items in by_host.items():
        headers = {
            # One token per push service, shared by all of its devices.
            'Authorization': f'vapid t={vapid_token(f"https://{host}", subject)}, k={key}',
            'TTL': str(ttl),
            'Urgency': urgency if urgency in ('very-low', 'low', 'normal', 'high') else 'normal',
            'Content-Length': '0',
            'User-Agent': 'ProjectSafezone (push relay)',
        }
        # Replaces an undelivered earlier push with the same topic, so a phone
        # that was off all day gets one reminder rather than a backlog.
        if topic and TOPIC_RE.match(topic):
            headers['Topic'] = topic
        count = max(1, min(config.PUSH_CONNECTIONS_PER_HOST, len(items)))
        for lane in range(count):
            lanes.append((host, headers, items[lane::count]))

    with ThreadPoolExecutor(max_workers=min(len(lanes), config.PUSH_MAX_WORKERS)) as pool:
        for lane_results in pool.map(lambda lane: _send_lane(*lane), lanes):
            for index, result, status in lane_results:
                results[index] = {'result': result, 'status': status}

    sent = sum(1 for r in results if r['result'] == 'ok')
    _log(f"Sent {sent} of {len(endpoints)} push(es) over {len(lanes)} connection(s)")
    return results

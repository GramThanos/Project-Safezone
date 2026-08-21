"""Outbound email: composed here, sent by the game-server.

This used to open an SMTP connection directly, which could never have worked in
the shipped topology - `backend` sits on the compose `internal` network, which
is declared `internal: true`, so it has neither egress nor DNS. Verification and
reset messages were being written to the container log and reported as sent.

So the split is the same one the Discord relay uses: **this composes, the
game-server sends** (`POST /api/mail`). Wording, links and templates stay here
where the product is; the SMTP credentials live in the one container that can
reach a mail server.

When no mail server is configured the message is logged and reported as sent,
which keeps local development and the shipped compose defaults working: a
developer who has not set up mail still gets a working signup, and the link they
need is in this container's log.
"""
import logging
import time

from flask import current_app

from src.utils.game_server import gs_request

logger = logging.getLogger(__name__)

# Whether the relay has a mail server is a deployment fact that changes at
# restart, not per request, and it is consulted on hot paths (every signup). A
# short cache keeps this from adding a round trip to each one, and a failed
# lookup is not cached so a relay that was briefly down does not leave the site
# believing mail is off for a minute.
_STATUS_TTL = 60
_status = {'configured': None, 'checked_at': 0.0}


def is_configured():
    """Whether a mail server has been set up, as far as the relay knows."""
    now = time.monotonic()
    if _status['configured'] is not None and now - _status['checked_at'] < _STATUS_TTL:
        return _status['configured']

    payload, status = gs_request('GET', '/api/mail')
    if status != 200:
        # Unknown, not "no". Reported as unconfigured for this call so the
        # caller degrades to logging, but not remembered.
        logger.warning('Could not ask the game-server whether mail is configured')
        return False

    configured = bool((payload.get('data') or {}).get('configured'))
    _status.update({'configured': configured, 'checked_at': now})
    return configured


def reset_cache():
    """Forget the cached relay status (for tests, and after a config change)."""
    _status.update({'configured': None, 'checked_at': 0.0})


def site_url():
    """Base URL the browser reaches this deployment on, for links in email."""
    return (current_app.config.get('SITE_URL') or '').rstrip('/')


def send(to_address, subject, body):
    """Send a plain-text message. Returns True if it was handed to a server.

    Never raises: a mail failure must not turn into a 500 on signup. The caller
    decides what to tell the user, and the failure is logged either way.
    """
    payload, status = gs_request('POST', '/api/mail', json={
        'to': to_address,
        'subject': subject,
        'body': body,
    })

    if status != 200:
        logger.error(f"Mail relay unreachable, not sending {subject!r} to {to_address}")
        return False

    if payload.get('ok'):
        return True

    if not payload.get('configured'):
        # No mail server on this deployment. Log the message so the link inside
        # it is still reachable, and report success - the alternative is a
        # signup that fails on a machine nobody has configured mail for.
        logger.warning(
            "SMTP is not configured; not sending %r to %s. Message body:\n%s",
            subject, to_address, body
        )
        _status.update({'configured': False, 'checked_at': time.monotonic()})
        return True

    logger.error(f"Failed to send mail to {to_address}: {payload.get('error')}")
    return False


def send_verification(to_address, username, token):
    """Ask a new account to confirm its address."""
    link = f"{site_url()}/verify?token={token}"
    return send(
        to_address,
        'Confirm your Safezone address',
        f"Hi {username},\n\n"
        f"Confirm this address to finish setting up your account:\n\n"
        f"{link}\n\n"
        f"The link is good for 24 hours. If you did not sign up, ignore this "
        f"message and nothing will happen.\n"
    )


def send_password_reset(to_address, username, token):
    """Send a reset link. Deliberately says nothing about whether an account exists."""
    link = f"{site_url()}/reset-password?token={token}"
    return send(
        to_address,
        'Reset your Safezone password',
        f"Hi {username},\n\n"
        f"Someone asked to reset the password on your account. Use this link to "
        f"choose a new one:\n\n"
        f"{link}\n\n"
        f"The link is good for one hour and can be used once. If this was not "
        f"you, ignore this message - your password has not changed.\n"
    )

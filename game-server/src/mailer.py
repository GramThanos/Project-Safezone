#!/usr/bin/env python3
"""Sending mail on the backend's behalf.

Same reason the Discord relay lives here: the backend sits on the compose
`internal` network, which is declared `internal: true` - no egress, no DNS - so
`smtplib.SMTP('smtp.example.com')` from there cannot resolve a host, let alone
connect to one. That was true of the account mail long before alerts existed;
verification and reset messages only ever reached the log.

So the SMTP credentials live in *this* container's environment, and the backend
posts a composed message to `/api/mail`. It composes, this sends.

Unlike the Discord relay there is no host allowlist, because there is nothing to
allow-list against: an operator's mail server is wherever they say it is. What
keeps this from being an open relay is that the endpoint is authenticated with
the manager token, and the recipient must be an address.

The caller may supply the SMTP server to use, which the backend does when an
admin has configured mail in the panel rather than in this container's
environment. That is a deliberate widening: the value comes from an
admin-only settings screen behind the manager token, and it is the same trust
level as putting it in the environment here. It does mean this endpoint can be
made to open a TCP connection to a host of the caller's choosing, so the token
guarding it matters as much as it does for everything else the manager exposes.

stdlib `smtplib`, no dependency added.
"""
import datetime
import re
import smtplib
from email.message import EmailMessage

import config

# Loose on purpose: this catches a malformed call, not every RFC violation. The
# mail server decides whether an address exists.
ADDRESS_RE = re.compile(r'^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$')


def _log(message):
    ts = datetime.datetime.now().isoformat()
    print(f"[{ts}][Mailer] {message}")


def settings_from(overrides=None):
    """The SMTP settings to use: the caller's if given, else this container's."""
    if overrides and (overrides.get('host') or '').strip():
        return {
            'host': str(overrides['host']).strip(),
            'port': int(overrides.get('port') or 587),
            'user': str(overrides.get('user') or ''),
            'password': str(overrides.get('password') or ''),
            'tls': bool(overrides.get('tls', True)),
            'from': str(overrides.get('from') or ''),
        }
    return {
        'host': config.SMTP_HOST,
        'port': config.SMTP_PORT,
        'user': config.SMTP_USER,
        'password': config.SMTP_PASSWORD,
        'tls': config.SMTP_TLS,
        'from': config.SMTP_FROM,
    }


def is_configured(overrides=None):
    """Whether a mail server has been set up, by either route."""
    try:
        return bool(settings_from(overrides)['host'])
    except (TypeError, ValueError):
        return False


def is_address(value):
    """Whether this is something we are willing to put in a To: header."""
    return bool(value and isinstance(value, str) and len(value) <= 254
                and ADDRESS_RE.match(value.strip()))


def send(to_address, subject, body, overrides=None):
    """Send one plain-text message. Returns ``(ok, error)``. Never raises.

    When SMTP is not configured this reports *not configured* rather than
    failing, and the backend logs the message instead - which is what keeps
    local development working: a developer who has not set up mail still gets a
    working signup, and the verification link is in a container log.
    """
    try:
        smtp = settings_from(overrides)
    except (TypeError, ValueError) as e:
        return False, f'Unusable SMTP settings: {e}'

    if not smtp['host']:
        return False, 'SMTP is not configured'
    if not is_address(to_address):
        return False, 'Not an email address'

    message = EmailMessage()
    message['Subject'] = subject or '(no subject)'
    message['From'] = smtp['from'] or smtp['user'] or 'safezone@localhost'
    message['To'] = to_address.strip()
    message.set_content(body or '')

    try:
        with smtplib.SMTP(smtp['host'], smtp['port'],
                          timeout=config.SMTP_TIMEOUT) as server:
            if smtp['tls']:
                server.starttls()
            if smtp['user']:
                server.login(smtp['user'], smtp['password'] or '')
            server.send_message(message)
        return True, None
    except Exception as e:
        _log(f"ERROR: failed to send to {to_address}: {e}")
        return False, str(e)[:300]

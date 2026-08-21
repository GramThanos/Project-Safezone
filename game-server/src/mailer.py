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
the manager token, the recipient must be an address, and the server it connects
to is fixed by configuration rather than chosen by the caller.

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


def is_configured():
    """Whether a mail server has been set up."""
    return bool(config.SMTP_HOST)


def is_address(value):
    """Whether this is something we are willing to put in a To: header."""
    return bool(value and isinstance(value, str) and len(value) <= 254
                and ADDRESS_RE.match(value.strip()))


def send(to_address, subject, body):
    """Send one plain-text message. Returns ``(ok, error)``. Never raises.

    When SMTP is not configured this reports *not configured* rather than
    failing, and the backend logs the message instead - which is what keeps
    local development working: a developer who has not set up mail still gets a
    working signup, and the verification link is in a container log.
    """
    if not is_configured():
        return False, 'SMTP is not configured'
    if not is_address(to_address):
        return False, 'Not an email address'

    message = EmailMessage()
    message['Subject'] = subject or '(no subject)'
    message['From'] = config.SMTP_FROM or config.SMTP_USER or 'safezone@localhost'
    message['To'] = to_address.strip()
    message.set_content(body or '')

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT,
                          timeout=config.SMTP_TIMEOUT) as server:
            if config.SMTP_TLS:
                server.starttls()
            if config.SMTP_USER:
                server.login(config.SMTP_USER, config.SMTP_PASSWORD or '')
            server.send_message(message)
        return True, None
    except Exception as e:
        _log(f"ERROR: failed to send to {to_address}: {e}")
        return False, str(e)[:300]

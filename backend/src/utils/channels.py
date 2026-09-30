"""The three places an alert can go, and how each one is written.

One event, three renderings, on purpose. A Discord channel gets an embed with a
colour and named fields. The staff feed gets one row, shared by everyone who can
read it, with a link into the panel. An ops mailbox gets plain text that has to
make sense on a phone at 3am with no context around it.

`deliver()` is the only entry point; `alerting.py` decides *who*, this decides
*how*. Adding a fourth kind of channel means adding a sender here and a row in
`KINDS` - not another event list.

**Internal versus external is a real distinction here.** `detail` - the opening
lines of a report, say - reaches the feed and the mailbox and never leaves the
deployment. Discord channels frequently have a wider membership than the staff
table does, so what goes there is deliberately thinner.
"""
import logging
import re

from src.models.staff_alert import StaffAlert
from src.utils import mailer, settings

logger = logging.getLogger(__name__)

# Delivery kinds, and what the panel calls them.
KIND_WEBHOOK = 'webhook'
KIND_INAPP = 'inapp'
KIND_EMAIL = 'email'
KINDS = [KIND_WEBHOOK, KIND_INAPP, KIND_EMAIL]

# Deliberately loose: this catches a typed mistake, not every RFC violation.
# The mail server is the real judge of whether an address exists.
EMAIL_RE = re.compile(r'^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$')


# Where a webhook target may point. Checked again by the relay in the
# game-server container, which is the boundary that actually matters - this copy
# is here so a typo is a red field in the panel rather than a delivery failure
# discovered three days later.
DISCORD_HOSTS = {'discord.com', 'discordapp.com', 'ptb.discord.com', 'canary.discord.com'}


def is_discord_url(url):
    """Whether this looks like a Discord webhook endpoint."""
    from urllib.parse import urlsplit

    if not url or not isinstance(url, str) or len(url) > 255:
        return False
    parts = urlsplit(url.strip())
    if parts.scheme != 'https' or parts.port not in (None, 443):
        return False
    return ((parts.hostname or '').lower() in DISCORD_HOSTS
            and parts.path.startswith('/api/webhooks/'))


def split_addresses(target):
    """The addresses in an email channel's target, comma or whitespace separated."""
    return [part for part in re.split(r'[,;\s]+', (target or '').strip()) if part]


def valid_addresses(target):
    """``(addresses, error)`` for an email channel's target."""
    addresses = split_addresses(target)
    if not addresses:
        return None, 'At least one address is required'
    bad = [a for a in addresses if not EMAIL_RE.match(a)]
    if bad:
        return None, f"That does not look like an address: {', '.join(bad[:3])}"
    if len(addresses) > 10:
        return None, 'Ten addresses is the limit - use a mailing list beyond that'
    return addresses, None


def _body(message, include_detail):
    """Everything below the title, as plain text. None when there is nothing."""
    parts = []
    if message.get('description'):
        parts.append(str(message['description']))
    if include_detail and message.get('detail'):
        parts.append(str(message['detail']))
    fields = message.get('fields') or []
    if fields:
        parts.append('\n'.join(f'{name}: {value}' for name, value in fields))
    return '\n\n'.join(parts) or None


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------

def _send_webhook(channel, message):
    """Relay an embed to a Discord webhook.

    Through the game-server, because this container has no egress at all - see
    `game-server/src/webhook.py` for why that relay refuses to post anywhere but
    Discord's own hosts.
    """
    from src.utils.game_server import gs_request

    brand = settings.get('site_brand_name') or 'Safezone'
    embed = {
        'title': str(message['title'])[:256],
        'color': message.get('color'),
        'timestamp': _now_iso(),
        'footer': {'text': f"{brand} · {message['event']}"},
    }
    if message.get('description'):
        embed['description'] = str(message['description'])[:2000]
    fields = message.get('fields') or []
    if fields:
        embed['fields'] = [{
            'name': str(name)[:256],
            'value': str(value)[:1024] or '—',
            'inline': True,
        } for name, value in fields][:25]

    # `username` renames the integration in the channel, so several deployments
    # posting into one server are told apart without opening the message.
    payload = {'username': brand[:80], 'embeds': [embed]}

    result, status = gs_request('POST', '/api/webhook',
                                json={'url': channel.target, 'payload': payload})
    if status != 200:
        return False, str(result.get('error') or f'relay returned {status}')[:500], None

    discord_status = result.get('status')
    if not result.get('ok'):
        detail = result.get('error') or f'Discord returned {discord_status}'
        return False, str(detail)[:500], discord_status
    return True, None, discord_status


def _now_iso():
    from datetime import datetime
    return datetime.utcnow().isoformat() + 'Z'


# ---------------------------------------------------------------------------
# The staff feed
# ---------------------------------------------------------------------------

def _send_inapp(session, channel, message):
    """Append one row to the staff feed.

    One row, not one per moderator. The message is identical for everybody who
    can read it, so writing it per-person was pure amplification - ten
    moderators meant ten rows per player join - and it put staff alerts in the
    same inbox, and the same unread badge, as the messages a player gets about
    their own account. Those are different things and they now live in different
    places; `users.staff_alerts_read_at` carries the only part that really is
    per-person.

    Uses the caller's session, so the row commits with whatever transaction the
    event happened in. `detail` is included: this never leaves the deployment,
    and a moderator reading "a report was filed" without the opening lines has
    to go and look it up, which is the friction this is supposed to remove.
    """
    session.add(StaffAlert(
        event=message.get('event') or 'unknown',
        title=str(message['title'])[:140],
        body=_body(message, include_detail=True),
        link=message.get('link'),
        server_id=message.get('server_id'),
    ))
    return True, None, None


# ---------------------------------------------------------------------------
# Mail
# ---------------------------------------------------------------------------

def _send_email(channel, message):
    """Mail an ops address.

    Addresses are typed in the panel rather than derived from the staff table:
    an alert should not depend on who happens to hold a role this week, or on
    their address being verified, and a demotion should not silently stop the
    3am mail from arriving anywhere.
    """
    addresses, error = valid_addresses(channel.target)
    if error:
        return False, error, None

    # `mailer.send` reports success when there is no mail server, so that a
    # signup on an unconfigured deployment still works and the link lands in the
    # log. That is the right answer for account mail and the wrong one here: an
    # ops mailbox that silently reports "delivered" into an empty void is worse
    # than one that says it is not set up.
    if not mailer.is_configured():
        return False, 'No mail server is configured for this deployment', None

    brand = settings.get('site_brand_name') or 'Safezone'
    detail = _body(message, include_detail=True)
    body = f"{message['title']}\n\n{detail}" if detail else str(message['title'])

    link = message.get('link')
    if link:
        base = mailer.site_url()
        if base:
            body = f'{body}\n\n{base}{link}'

    failed = []
    for address in addresses:
        if not mailer.send(address, f"[{brand}] {message['title']}", body):
            failed.append(address)

    if failed:
        return False, f"Mail failed for: {', '.join(failed)}", None
    return True, None, None


# ---------------------------------------------------------------------------

def deliver(session, channel, message):
    """Send one message down one channel. Returns ``(ok, error, status)``.

    ``status`` is a transport-specific code when there is one - Discord's HTTP
    status - and None otherwise. Never raises: a channel that explodes must not
    take the other channels, or the event, down with it.
    """
    try:
        if channel.kind == KIND_WEBHOOK:
            return _send_webhook(channel, message)
        if channel.kind == KIND_INAPP:
            return _send_inapp(session, channel, message)
        if channel.kind == KIND_EMAIL:
            return _send_email(channel, message)
        return False, f"Unknown channel kind '{channel.kind}'", None
    except Exception as e:
        logger.error(f"Channel '{channel.name}' ({channel.kind}) raised: {e}")
        return False, str(e)[:500], None

"""A small self-hosted CAPTCHA for the signup form.

Deliberately not a third-party widget: the frontend currently loads nothing from
outside its own origin, and signup is exactly the page where you would least
like to hand a tracker every visitor.

Be honest about what this is. It stops commodity signup bots that POST the form
directly; it will not stop somebody who writes ten lines of OCR against it. That
is the right trade for a game-server panel, where the realistic threat is drive-by
automation rather than a targeted attacker. The registration gate (closing
signups, a shared password, invitations) is the real control.

The challenge is drawn as an SVG so there is no image dependency, and the answer
lives only in Redis - never in the page, and never in a signed token the client
could unpack.
"""
import logging
import random
import secrets

from flask import current_app

from src.utils.redis_utils import get_redis_connection

logger = logging.getLogger(__name__)

# No 0/O/1/I/l - a person cannot reliably tell them apart in a distorted glyph,
# and a challenge you fail by reading it correctly is just a broken form.
ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'
LENGTH = 5
TTL_SECONDS = 600
KEY_PREFIX = 'captcha:'


def is_enabled():
    try:
        from src.utils import settings
        return bool(settings.get('captcha_enabled'))
    except Exception:
        return bool(current_app.config.get('CAPTCHA_ENABLED'))


def _render(code):
    """Draw the code as a standalone SVG, with enough noise to defeat a crop."""
    rng = random.SystemRandom()
    width, height = 200, 64
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="verification code">',
        f'<rect width="{width}" height="{height}" fill="#1b1f19"/>',
    ]

    # Noise behind the glyphs, so a naive threshold-and-crop does not isolate them.
    for _ in range(6):
        x1, y1 = rng.randint(0, width), rng.randint(0, height)
        x2, y2 = rng.randint(0, width), rng.randint(0, height)
        parts.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="#55663e" stroke-width="{rng.choice([1, 2])}" opacity="0.7"/>'
        )

    step = width // (len(code) + 1)
    for index, char in enumerate(code):
        x = step * (index + 1) + rng.randint(-6, 6)
        y = height // 2 + rng.randint(-4, 8)
        rotation = rng.randint(-28, 28)
        size = rng.randint(28, 36)
        parts.append(
            f'<text x="{x}" y="{y}" fill="#e6e8e1" font-size="{size}" '
            f'font-family="Georgia, serif" font-weight="bold" text-anchor="middle" '
            f'dominant-baseline="middle" transform="rotate({rotation} {x} {y})">{char}</text>'
        )

    for _ in range(2):
        y = rng.randint(0, height)
        parts.append(
            f'<line x1="0" y1="{y}" x2="{width}" y2="{rng.randint(0, height)}" '
            f'stroke="#8e3520" stroke-width="2" opacity="0.6"/>'
        )

    parts.append('</svg>')
    return ''.join(parts)


def issue():
    """Create a challenge. Returns ``(challenge_id, svg)`` or ``None`` if unavailable."""
    code = ''.join(secrets.choice(ALPHABET) for _ in range(LENGTH))
    challenge_id = secrets.token_urlsafe(16)
    try:
        client = get_redis_connection()
        client.setex(f'{KEY_PREFIX}{challenge_id}', TTL_SECONDS, code)
    except Exception as e:
        logger.error(f"Could not store captcha challenge: {e}")
        return None
    return challenge_id, _render(code)


def verify(challenge_id, answer):
    """Check and consume an answer. A challenge is good for exactly one attempt.

    Returns False when Redis is unreachable: a verification that cannot be
    performed has not succeeded, and failing open here would quietly remove the
    only barrier on the form.
    """
    if not challenge_id or not answer:
        return False
    try:
        client = get_redis_connection()
        key = f'{KEY_PREFIX}{challenge_id}'
        expected = client.get(key)
        # Consume regardless of the outcome, so a wrong answer cannot be retried
        # against the same challenge until it lands.
        client.delete(key)
    except Exception as e:
        logger.error(f"Could not verify captcha: {e}")
        return False

    if expected is None:
        return False
    if isinstance(expected, bytes):
        expected = expected.decode('utf-8')
    return secrets.compare_digest(expected.upper(), str(answer).strip().upper())

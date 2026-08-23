"""Time-based one-time passwords (RFC 6238), implemented on the standard library.

A TOTP authenticator app and this server share a secret. Both derive the same
six-digit code from that secret and the current 30-second window, so the code a
person reads off their phone proves they hold the secret without it ever
crossing the wire. That is the whole of second-factor auth here.

No third-party package for this on purpose. The algorithm is an HMAC and a
truncation - a few lines of `hmac`/`hashlib` - and pulling in a dependency for
it would be more surface to trust than the thing it replaces. The one piece that
is genuinely fiddly, base32 with the right padding, is `base64` from the stdlib.

The generated QR/secret is rendered by the frontend from `provisioning_uri`; the
secret itself never leaves as anything but the otpauth string the user is about
to scan.
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

# 30 seconds is the near-universal default every authenticator app assumes, and
# it is not advertised in the provisioning URI's common form - so it has to
# match what the apps expect rather than being a free choice.
STEP_SECONDS = 30
DIGITS = 6
# 20 bytes = 160 bits, the RFC's recommended secret length for SHA-1 HMAC, and
# what Google Authenticator and its clones assume when a URI omits the length.
SECRET_BYTES = 20


def generate_secret():
    """A fresh base32 secret, in the unpadded upper-case form apps expect."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode('ascii').rstrip('=')


def _code_at(secret, counter):
    """The HOTP value for a base32 `secret` at integer `counter` (RFC 4226)."""
    # Authenticators write secrets without padding; b32decode demands it back.
    padded = secret.strip().replace(' ', '').upper()
    padded += '=' * ((8 - len(padded) % 8) % 8)
    try:
        key = base64.b32decode(padded, casefold=True)
    except Exception:
        return None
    digest = hmac.new(key, struct.pack('>Q', counter), hashlib.sha1).digest()
    # Dynamic truncation: the low nibble of the last byte picks a 4-byte window.
    offset = digest[-1] & 0x0F
    truncated = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10 ** DIGITS)).zfill(DIGITS)


def verify(secret, code, window=1, at=None):
    """True when `code` is valid for `secret` right now.

    `window` accepts codes from that many steps on either side of the current
    one, so a code typed as its 30-second window rolls over, or a phone clock a
    little off true, still passes. One step (±30s) is the usual tolerance.

    Constant-time compared, and the shape of `code` is checked first so a
    non-numeric or wrong-length answer is rejected without touching the secret.
    """
    if not secret or not code:
        return False
    code = str(code).strip()
    if len(code) != DIGITS or not code.isdigit():
        return False

    now = int(at if at is not None else time.time())
    counter = now // STEP_SECONDS
    for drift in range(-window, window + 1):
        expected = _code_at(secret, counter + drift)
        if expected is not None and hmac.compare_digest(expected, code):
            return True
    return False


def provisioning_uri(secret, account_name, issuer):
    """The otpauth:// URI an authenticator app turns into an account.

    `issuer` appears both as a label prefix and as a parameter; apps read the
    parameter, but the prefix is what a person sees in the list, so both carry it
    and they must agree.
    """
    label = quote(f'{issuer}:{account_name}')
    params = urlencode({
        'secret': secret,
        'issuer': issuer,
        'algorithm': 'SHA1',
        'digits': DIGITS,
        'period': STEP_SECONDS,
    })
    return f'otpauth://totp/{label}?{params}'

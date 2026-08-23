"""Tests for the TOTP second factor.

The algorithm is the load-bearing part - a code that verifies wrongly either
locks everyone out or lets anyone in - so it is pinned against the RFC 6238
reference vector rather than only round-tripped against itself. Round-tripping a
broken implementation against its own broken output proves nothing.
"""
import base64
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.utils import totp  # noqa: E402


# RFC 6238 Appendix B publishes expected TOTP values for the ASCII secret
# "12345678901234567890" using SHA-1. Our secrets are base32, so encode that
# ASCII key the same way an authenticator would store it.
RFC_SECRET = base64.b32encode(b'12345678901234567890').decode('ascii')


class TestTotpAgainstRfcVector(unittest.TestCase):
    def test_known_vectors(self):
        # (unix time, expected 8-digit code); we take the low 6, our digit count.
        cases = [
            (59, '287082'),
            (1111111109, '081804'),
            (1234567890, '005924'),
            (2000000000, '279037'),
        ]
        for at, expected in cases:
            self.assertTrue(
                totp.verify(RFC_SECRET, expected, window=0, at=at),
                f'expected {expected} to verify at t={at}')

    def test_wrong_code_is_rejected(self):
        self.assertFalse(totp.verify(RFC_SECRET, '000000', window=0, at=59))


class TestTotpShape(unittest.TestCase):
    """Malformed answers are turned away before the secret is touched."""

    def test_rejects_non_numeric_and_wrong_length(self):
        for bad in ('', '12345', '1234567', 'abcdef', '12 34 56', None):
            self.assertFalse(totp.verify(RFC_SECRET, bad, at=59))

    def test_empty_secret_never_verifies(self):
        self.assertFalse(totp.verify('', '287082', at=59))
        self.assertFalse(totp.verify(None, '287082', at=59))


class TestTotpWindow(unittest.TestCase):
    """A code stays valid for one step on either side, so a rollover mid-entry
    or a slightly wrong phone clock still passes."""

    def test_neighbouring_step_accepted_within_window(self):
        secret = totp.generate_secret()
        # The code for the *previous* 30s step must still verify now.
        prev = totp._code_at(secret, (100000 // totp.STEP_SECONDS) - 1)
        self.assertTrue(totp.verify(secret, prev, window=1, at=100000))

    def test_far_step_rejected(self):
        secret = totp.generate_secret()
        far = totp._code_at(secret, (100000 // totp.STEP_SECONDS) - 5)
        self.assertFalse(totp.verify(secret, far, window=1, at=100000))


class TestGeneratedSecret(unittest.TestCase):
    def test_secret_is_unpadded_base32(self):
        secret = totp.generate_secret()
        self.assertNotIn('=', secret)
        # Decodable once padding is restored - the property enable/verify rely on.
        padded = secret + '=' * ((8 - len(secret) % 8) % 8)
        base64.b32decode(padded, casefold=True)


class TestProvisioningUri(unittest.TestCase):
    def test_uri_carries_secret_and_issuer(self):
        uri = totp.provisioning_uri('ABCDEF', 'alice', 'Safezone')
        self.assertTrue(uri.startswith('otpauth://totp/'))
        self.assertIn('secret=ABCDEF', uri)
        self.assertIn('issuer=Safezone', uri)
        # The label prefix and the issuer parameter must agree.
        self.assertIn('Safezone%3Aalice', uri)


if __name__ == '__main__':
    unittest.main()

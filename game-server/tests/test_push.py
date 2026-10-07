"""Tests for the push relay: the endpoint allowlist, the VAPID token, the key.

The endpoint is a URL a player's browser hands us, so what the relay refuses
matters more than what it sends - the same stance as the Discord relay's tests.
"""
import base64
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import config  # noqa: E402
import push  # noqa: E402

from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature  # noqa: E402


def _unb64(text):
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


class TestIsPushEndpoint(unittest.TestCase):
    def test_accepts_the_browser_push_services(self):
        for url in (
            'https://fcm.googleapis.com/fcm/send/abc:APA91b-def',
            'https://updates.push.services.mozilla.com/wpush/v2/gAAAAA',
            'https://web.push.apple.com/QGxxx-yyy',
            'https://wns2-par02p.notify.windows.com/w/?token=BQYAAA',
        ):
            self.assertTrue(push.is_push_endpoint(url), msg=url)

    def test_rejects_plain_http(self):
        self.assertFalse(push.is_push_endpoint('http://fcm.googleapis.com/fcm/send/x'))

    def test_rejects_other_hosts(self):
        self.assertFalse(push.is_push_endpoint('https://example.com/fcm/send/x'))

    def test_rejects_lookalike_hosts(self):
        for url in (
            'https://fcm.googleapis.com.evil.test/x',
            'https://evilpush.apple.com.test/x',
            'https://notify.windows.com.evil.test/x',
            # The bare suffix is not a push host.
            'https://push.apple.com/x',
        ):
            self.assertFalse(push.is_push_endpoint(url), msg=url)

    def test_rejects_suffix_without_its_dot(self):
        self.assertFalse(push.is_push_endpoint('https://evilnotify.windows.com/x'))

    def test_rejects_credentials_in_netloc(self):
        self.assertFalse(push.is_push_endpoint('https://fcm.googleapis.com@evil.test/x'))
        self.assertFalse(push.is_push_endpoint('https://user:pw@fcm.googleapis.com/x'))

    def test_rejects_other_ports(self):
        self.assertFalse(push.is_push_endpoint('https://fcm.googleapis.com:8443/x'))
        self.assertFalse(push.is_push_endpoint('https://fcm.googleapis.com:bad/x'))

    def test_rejects_internal_addresses(self):
        for url in ('https://169.254.169.254/x', 'https://localhost/x',
                    'https://backend:5000/x', 'https://10.0.0.1/x'):
            self.assertFalse(push.is_push_endpoint(url), msg=url)

    def test_rejects_junk(self):
        for value in (None, '', 42, 'not a url', 'https://fcm.googleapis.com/' + 'x' * 1100):
            self.assertFalse(push.is_push_endpoint(value), msg=repr(value)[:40])


class KeyFileTestCase(unittest.TestCase):
    """Each test gets its own key file, and a cold module-level cache."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, 'keys', 'vapid.pem')
        patcher = mock.patch.object(config, 'PUSH_VAPID_KEY_FILE', self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        push._key = None
        self.addCleanup(setattr, push, '_key', None)
        self.addCleanup(self.dir.cleanup)


class TestKey(KeyFileTestCase):
    def test_created_on_first_use_and_kept(self):
        first = push.public_key()
        self.assertTrue(os.path.exists(self.path))
        # A restart reads the same key back rather than minting a new one,
        # which would silently invalidate every browser's subscription.
        push._key = None
        self.assertEqual(push.public_key(), first)

    def test_public_key_is_an_uncompressed_p256_point(self):
        point = _unb64(push.public_key())
        self.assertEqual(len(point), 65)
        self.assertEqual(point[0], 0x04)

    @unittest.skipIf(os.name == 'nt', 'POSIX permissions')
    def test_key_file_is_owner_only(self):
        push.public_key()
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)


class TestVapidToken(KeyFileTestCase):
    def test_claims(self):
        token = push.vapid_token('https://fcm.googleapis.com', 'mailto:ops@example.com', now=1000)
        header, claims, _sig = token.split('.')
        self.assertEqual(json.loads(_unb64(header)), {'typ': 'JWT', 'alg': 'ES256'})
        self.assertEqual(json.loads(_unb64(claims)), {
            'aud': 'https://fcm.googleapis.com',
            'exp': 1000 + push.TOKEN_LIFETIME,
            'sub': 'mailto:ops@example.com',
        })

    def test_signature_verifies_against_the_public_key(self):
        token = push.vapid_token('https://web.push.apple.com', 'mailto:ops@example.com')
        header, claims, sig = token.split('.')
        raw = _unb64(sig)
        self.assertEqual(len(raw), 64)
        der = encode_dss_signature(int.from_bytes(raw[:32], 'big'), int.from_bytes(raw[32:], 'big'))
        public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), _unb64(push.public_key()))
        # Raises InvalidSignature if the token was not signed by our key.
        public.verify(der, f'{header}.{claims}'.encode(), ec.ECDSA(hashes.SHA256()))

    def test_lifetime_within_the_rfc_limit(self):
        self.assertLessEqual(push.TOKEN_LIFETIME, 24 * 3600)


class TestSubject(unittest.TestCase):
    def test_keeps_mailto_and_https(self):
        self.assertEqual(push.subject_or_default('mailto:a@b.c'), 'mailto:a@b.c')
        self.assertEqual(push.subject_or_default('https://play.example.com'), 'https://play.example.com')

    def test_falls_back_for_anything_else(self):
        for value in (None, '', 'http://localhost:8080', 'javascript:alert(1)', 42):
            self.assertEqual(push.subject_or_default(value), config.PUSH_SUBJECT, msg=repr(value))


class TestSendMany(KeyFileTestCase):
    def test_refused_endpoints_are_reported_without_any_connection(self):
        with mock.patch.object(push.http.client, 'HTTPSConnection') as conn:
            results = push.send_many(['https://evil.test/x', 'http://fcm.googleapis.com/x'])
        conn.assert_not_called()
        self.assertEqual([r['result'] for r in results], ['invalid', 'invalid'])

    def test_results_keep_the_callers_order_and_share_connections(self):
        responses = {'/a': 201, '/b': 410, '/c': 429, '/d': 404}

        class FakeResponse:
            def __init__(self, status):
                self.status = status
                self.will_close = False

            def read(self):
                return b''

        class FakeConnection:
            opened = []

            def __init__(self, host, port, timeout=None):
                self.host = host
                FakeConnection.opened.append(host)

            def request(self, method, path, body=None, headers=None):
                assert method == 'POST' and body == b''
                assert headers['Authorization'].startswith('vapid t=')
                assert headers['Topic'] == 'daily-crate'
                self.path = path

            def getresponse(self):
                return FakeResponse(responses[self.path])

            def close(self):
                pass

        endpoints = [
            'https://fcm.googleapis.com/a',
            'https://example.com/nope',
            'https://fcm.googleapis.com/b',
            'https://updates.push.services.mozilla.com/c',
            'https://fcm.googleapis.com/d',
        ]
        with mock.patch.object(config, 'PUSH_CONNECTIONS_PER_HOST', 1), \
                mock.patch.object(push.http.client, 'HTTPSConnection', FakeConnection):
            results = push.send_many(endpoints, ttl=3600, topic='daily-crate')

        self.assertEqual([r['result'] for r in results],
                         ['ok', 'invalid', 'gone', 'failed', 'gone'])
        # Three Google devices down one connection, one Mozilla device down another.
        self.assertEqual(sorted(FakeConnection.opened),
                         ['fcm.googleapis.com', 'updates.push.services.mozilla.com'])


if __name__ == '__main__':
    unittest.main()

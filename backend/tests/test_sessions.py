"""Tests for sliding sessions: what a refresh keeps, and how long each kind lasts.

A session lasts a lifetime from its last use, and the client refreshes it as it
is used. Two properties make that safe to tie other things to:

  * **A refresh keeps the session.** The `sid` carries over, so a device's push
    subscription follows the session rather than the token; a fresh sign-in
    starts a new one.
  * **The installed app gets its own lifetime.** Declared by the client with
    `X-Client: app`, and sized by the admin's setting, not by the website's.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest import mock

from flask import Flask

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.middleware import auth  # noqa: E402

CONFIG = {
    'SECRET_KEY': 'test-secret',
    'TOKEN_ISSUER': 'test-issuer',
    'TOKEN_AUDIENCE': 'test-audience',
    'TOKEN_EXPIRY_HOURS': 24,
    'APP_SESSION_DAYS': 30,
}


class SessionTestCase(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(CONFIG)
        # Settings unreachable: the environment defaults above apply.
        patcher = mock.patch('src.utils.settings.get', side_effect=RuntimeError('no db'))
        patcher.start()
        self.addCleanup(patcher.stop)

    def issue(self, headers=None, **kwargs):
        with self.app.test_request_context(headers=headers or {}):
            token = auth.generate_token(7, 'alice', 'player', 2,
                                        installed=auth.request_installed(), **kwargs)
            return token, auth.decode_token(token)

    def lifetime(self, claims):
        return timedelta(seconds=claims['exp'] - claims['iat'])


class TestSessions(SessionTestCase):
    def test_a_sign_in_starts_a_session(self):
        _, first = self.issue()
        _, second = self.issue()
        self.assertTrue(first['sid'])
        self.assertNotEqual(first['sid'], second['sid'])

    def test_a_refresh_keeps_it(self):
        _, claims = self.issue(sid='abc')
        self.assertEqual(claims['sid'], 'abc')
        self.assertEqual(auth.session_id(claims), 'abc')

    def test_tokens_from_before_sessions_use_their_jti(self):
        self.assertEqual(auth.session_id({'jti': 'j'}), 'j')

    def test_website_lifetime(self):
        _, claims = self.issue()
        self.assertFalse(claims['app'])
        self.assertEqual(self.lifetime(claims), timedelta(hours=24))

    def test_installed_app_lifetime(self):
        _, claims = self.issue(headers={'X-Client': 'app'})
        self.assertTrue(claims['app'])
        self.assertEqual(self.lifetime(claims), timedelta(days=30))

    def test_anything_else_is_the_website(self):
        _, claims = self.issue(headers={'X-Client': 'application'})
        self.assertFalse(claims['app'])

    def test_settings_win_over_the_environment(self):
        values = {'token_expiry_hours': 6, 'app_session_days': 90}
        with mock.patch('src.utils.settings.get', side_effect=values.get):
            _, web = self.issue()
            _, app = self.issue(headers={'X-Client': 'app'})
        self.assertEqual(self.lifetime(web), timedelta(hours=6))
        self.assertEqual(self.lifetime(app), timedelta(days=90))

    def test_a_fresh_token_is_not_renewed_by_a_check(self):
        _, claims = self.issue()
        with self.app.test_request_context():
            self.assertFalse(auth.token_needs_renewal(claims, now=claims['iat'] + 600))

    def test_an_hour_old_token_is_renewed(self):
        _, claims = self.issue()
        with self.app.test_request_context():
            self.assertTrue(auth.token_needs_renewal(claims, now=claims['iat'] + 3600))

    def test_half_a_short_lifetime_is_enough(self):
        # An admin who set sessions to an hour: renewing only at the hour
        # would let every session lapse before its first renewal.
        claims = {'iat': 1000, 'exp': 1000 + 3600, 'app': False}
        with self.app.test_request_context():
            self.assertFalse(auth.token_needs_renewal(claims, now=1000 + 1700))
            self.assertTrue(auth.token_needs_renewal(claims, now=1000 + 1800))

    def test_opening_from_the_home_screen_renews_at_once(self):
        _, claims = self.issue()
        with self.app.test_request_context(headers={'X-Client': 'app'}):
            self.assertTrue(auth.token_needs_renewal(claims, now=claims['iat'] + 1))

    def test_token_expiry_reads_back_the_exp(self):
        token, claims = self.issue()
        self.assertEqual(auth.token_expiry(token), datetime.utcfromtimestamp(claims['exp']))


if __name__ == '__main__':
    unittest.main()

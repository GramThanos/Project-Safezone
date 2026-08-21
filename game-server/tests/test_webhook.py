"""Tests for the Discord relay's URL allowlist (the egress boundary).

This is the one place in the stack where a value stored in the backend's
database turns into an outbound request, so what it refuses matters more than
what it sends.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import webhook  # noqa: E402


class TestIsWebhookUrl(unittest.TestCase):
    def test_accepts_discord_webhook(self):
        self.assertTrue(webhook.is_webhook_url(
            'https://discord.com/api/webhooks/123456789/abcDEF-token_123'))

    def test_accepts_legacy_and_beta_hosts(self):
        for host in ('discordapp.com', 'ptb.discord.com', 'canary.discord.com'):
            self.assertTrue(webhook.is_webhook_url(f'https://{host}/api/webhooks/1/tok'),
                            msg=host)

    def test_rejects_plain_http(self):
        self.assertFalse(webhook.is_webhook_url('http://discord.com/api/webhooks/1/tok'))

    def test_rejects_other_hosts(self):
        self.assertFalse(webhook.is_webhook_url('https://example.com/api/webhooks/1/tok'))

    def test_rejects_lookalike_host(self):
        # The suffix trick: a host that merely starts with discord.com.
        self.assertFalse(webhook.is_webhook_url('https://discord.com.evil.test/api/webhooks/1/t'))

    def test_rejects_credentials_in_netloc(self):
        # Reads as discord.com, resolves as evil.test.
        self.assertFalse(webhook.is_webhook_url('https://discord.com@evil.test/api/webhooks/1/t'))

    def test_rejects_internal_addresses(self):
        for url in ('https://169.254.169.254/api/webhooks/1/t',
                    'https://127.0.0.1/api/webhooks/1/t',
                    'https://game-server:5000/api/webhooks/1/t'):
            self.assertFalse(webhook.is_webhook_url(url), msg=url)

    def test_rejects_other_ports(self):
        self.assertFalse(webhook.is_webhook_url('https://discord.com:8443/api/webhooks/1/t'))

    def test_rejects_other_paths(self):
        for path in ('/api/users/@me', '/', '/api/webhooks'):
            self.assertFalse(webhook.is_webhook_url(f'https://discord.com{path}'), msg=path)

    def test_rejects_junk(self):
        for value in (None, '', 'not a url', 123, 'https://discord.com/api/webhooks/' + 'x' * 600):
            self.assertFalse(webhook.is_webhook_url(value), msg=repr(value))


class TestPost(unittest.TestCase):
    def test_refuses_before_sending(self):
        # No network involved: a rejected URL must not reach urlopen at all.
        ok, status, error = webhook.post('https://example.com/api/webhooks/1/t', {'a': 1})
        self.assertFalse(ok)
        self.assertIsNone(status)
        self.assertIn('Discord', error)

    def test_refuses_unserialisable_payload(self):
        ok, status, error = webhook.post('https://discord.com/api/webhooks/1/t',
                                         {'when': object()})
        self.assertFalse(ok)
        self.assertIsNone(status)


if __name__ == '__main__':
    unittest.main()

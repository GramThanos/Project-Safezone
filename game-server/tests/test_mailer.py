"""Tests for the mail relay's input checks.

The relay is authenticated and its server is fixed by configuration, so the
thing worth pinning down here is what it will put in a To: header - and that it
says "not configured" rather than pretending to send when no SMTP host is set.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import config  # noqa: E402
import mailer  # noqa: E402


class TestIsAddress(unittest.TestCase):
    def test_accepts_ordinary_addresses(self):
        for value in ('ops@example.com', 'a.b+tag@sub.example.co.uk'):
            self.assertTrue(mailer.is_address(value), msg=value)

    def test_rejects_junk(self):
        for value in (None, '', 'nonsense', 'a@b', 'a b@example.com',
                      'a@example.com, b@example.com', 123,
                      'a@' + 'x' * 300 + '.com'):
            self.assertFalse(mailer.is_address(value), msg=repr(value))

    def test_rejects_header_injection(self):
        # A newline in an address is how a second header gets appended.
        self.assertFalse(mailer.is_address('ops@example.com\nBcc: evil@example.test'))


class TestSendWithoutConfiguration(unittest.TestCase):
    def setUp(self):
        self._host = config.SMTP_HOST
        config.SMTP_HOST = ''

    def tearDown(self):
        config.SMTP_HOST = self._host

    def test_reports_not_configured_rather_than_failing(self):
        ok, error = mailer.send('ops@example.com', 'Subject', 'Body')
        self.assertFalse(ok)
        self.assertIn('not configured', error)

    def test_is_configured_follows_the_host(self):
        self.assertFalse(mailer.is_configured())
        config.SMTP_HOST = 'smtp.example.com'
        self.assertTrue(mailer.is_configured())


class TestSendValidatesBeforeConnecting(unittest.TestCase):
    def setUp(self):
        self._host = config.SMTP_HOST
        config.SMTP_HOST = 'smtp.invalid.test'

    def tearDown(self):
        config.SMTP_HOST = self._host

    def test_bad_address_never_opens_a_connection(self):
        # No network: this must be refused on the address alone.
        ok, error = mailer.send('not an address', 'Subject', 'Body')
        self.assertFalse(ok)
        self.assertEqual(error, 'Not an email address')


if __name__ == '__main__':
    unittest.main()

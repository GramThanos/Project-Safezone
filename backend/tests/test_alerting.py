"""Tests for alert routing: who hears an event, and what each channel is told.

Everything decided before anything is sent - which channels match, whether a
destination is allowed to be one, and which parts of a message are internal.
The sending itself needs the game-server, Discord and a mail server, so it is
not tested here.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.models.alert_channel import AlertChannel  # noqa: E402
from src.utils import alerting, channels  # noqa: E402


def make(**kwargs):
    values = {
        'kind': AlertChannel.KIND_WEBHOOK,
        'name': 'alerts',
        'target': 'https://discord.com/api/webhooks/123456/tokentokentoken',
        'events': ['player.join'],
        'enabled': True,
    }
    values.update(kwargs)
    return AlertChannel(**values)


class TestWants(unittest.TestCase):
    def test_subscribed_event(self):
        self.assertTrue(make().wants('player.join'))

    def test_unsubscribed_event(self):
        self.assertFalse(make().wants('player.leave'))

    def test_disabled_hears_nothing(self):
        self.assertFalse(make(enabled=False).wants('player.join'))

    def test_no_server_filter_means_every_server(self):
        row = make()
        self.assertTrue(row.wants('player.join', 1))
        self.assertTrue(row.wants('player.join', 99))

    def test_server_filter_excludes_others(self):
        row = make(server_ids=[2, 3])
        self.assertTrue(row.wants('player.join', 2))
        self.assertFalse(row.wants('player.join', 1))

    def test_unscoped_event_ignores_the_filter(self):
        # A signup does not happen on a server; a channel filtered to one
        # server should still hear about it if it asked for it.
        row = make(events=['user.signup'], server_ids=[2])
        self.assertTrue(row.wants('user.signup'))

    def test_every_catalog_event_is_matchable(self):
        for key in alerting.EVENTS:
            self.assertTrue(make(events=[key]).wants(key), msg=key)

    def test_matching_is_the_same_for_every_kind(self):
        # The kind decides how a message is written, never whether it is sent.
        for kind in AlertChannel.KINDS:
            self.assertTrue(make(kind=kind).wants('player.join'), msg=kind)


class TestMaskedTarget(unittest.TestCase):
    def test_hides_a_webhook_token(self):
        masked = make().masked_target()
        self.assertNotIn('tokentokentoken', masked)
        self.assertTrue(masked.startswith('https://discord.com/api/webhooks/123456/'))

    def test_shows_email_addresses(self):
        # Not a secret, and an operator has to be able to edit the list.
        row = make(kind=AlertChannel.KIND_EMAIL, target='ops@example.com')
        self.assertEqual(row.masked_target(), 'ops@example.com')

    def test_inbox_has_no_target(self):
        self.assertEqual(make(kind=AlertChannel.KIND_INAPP, target=None).masked_target(), '')

    def test_survives_a_url_without_a_token(self):
        self.assertEqual(make(target='nonsense').masked_target(), 'nonsense')


class TestDestinations(unittest.TestCase):
    def test_accepts_a_discord_url(self):
        self.assertTrue(channels.is_discord_url(
            'https://discord.com/api/webhooks/123/abc'))

    def test_rejects_non_discord_urls(self):
        for url in ('http://discord.com/api/webhooks/1/t',
                    'https://example.com/api/webhooks/1/t',
                    'https://discord.com@evil.test/api/webhooks/1/t',
                    'https://discord.com/api/users/@me',
                    '', None):
            self.assertFalse(channels.is_discord_url(url), msg=repr(url))

    def test_accepts_address_lists(self):
        addresses, error = channels.valid_addresses('a@example.com, b@example.com')
        self.assertIsNone(error)
        self.assertEqual(addresses, ['a@example.com', 'b@example.com'])

    def test_rejects_bad_addresses(self):
        for value in ('', None, 'nonsense', 'a@b', 'a@ b.com'):
            _, error = channels.valid_addresses(value)
            self.assertIsNotNone(error, msg=repr(value))

    def test_refuses_an_unreasonable_number_of_addresses(self):
        _, error = channels.valid_addresses(
            ', '.join(f'a{i}@example.com' for i in range(11)))
        self.assertIsNotNone(error)


class TestMessageRendering(unittest.TestCase):
    MESSAGE = {
        'title': 'New report from Bob',
        'description': 'A report was filed.',
        'detail': 'He kept driving into my base.',
        'fields': [('Kind', 'report'), ('From', 'Bob')],
    }

    def test_internal_channels_see_the_detail(self):
        body = channels._body(self.MESSAGE, include_detail=True)
        self.assertIn('driving into my base', body)

    def test_external_channels_do_not(self):
        # The whole point of `detail`: the text of a report reaches the staff
        # inbox and stops there.
        body = channels._body(self.MESSAGE, include_detail=False)
        self.assertNotIn('driving into my base', body)
        self.assertIn('A report was filed.', body)

    def test_empty_message_has_no_body(self):
        self.assertIsNone(channels._body({'title': 'Something happened'}, True))


class TestQueueRendering(unittest.TestCase):
    def test_join_names_the_player_and_server(self):
        title, _, fields = alerting._render({
            'event': 'player.join', 'server_name': 'Knox', 'player': 'Bob', 'online': 3
        })
        self.assertEqual(title, 'Bob joined Knox')
        self.assertIn(('Online now', 3), fields)

    def test_unknown_event_still_says_something(self):
        title, _, _ = alerting._render({'event': 'server.something', 'server_id': 4})
        self.assertIn('server 4', title)

    def test_stale_entries_are_dropped(self):
        self.assertTrue(alerting._too_old('2020-01-01T00:00:00.000000Z'))
        self.assertFalse(alerting._too_old(None))


class TestCatalog(unittest.TestCase):
    def test_every_event_declares_what_the_panel_needs(self):
        for event in alerting.describe():
            self.assertIn(event['group'], alerting.GROUP_ORDER, msg=event['key'])
            self.assertTrue(event['label'], msg=event['key'])
            self.assertIn(event['source'], ('site', 'game'), msg=event['key'])
            self.assertIn(event['volume'], ('low', 'high'), msg=event['key'])

    def test_game_events_are_all_server_scoped(self):
        # Anything the manager reports happened on one of its servers, so the
        # per-channel server filter has to apply to all of them.
        for event in alerting.describe():
            if event['source'] == 'game':
                self.assertTrue(event['scoped'], msg=event['key'])


if __name__ == '__main__':
    unittest.main()

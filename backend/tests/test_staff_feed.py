"""Tests for the staff feed: the split from player notifications.

Staff alerts used to be written as one `notifications` row per moderator, into
the same inbox and the same unread badge that tells a *player* their reward
arrived. They are now one shared `staff_alerts` row with a per-account read
marker.

Three properties are worth pinning, because getting any of them wrong puts the
old behaviour back:

  * **One row, whoever is on staff.** The count must not move with the number of
    moderators - that amplification is the thing being removed.
  * **Nothing lands in the player inbox.** An admin who is also a player must
    stop seeing deployment news in their own bell.
  * **`detail` still reaches it.** The feed is internal, and the whole reason a
    moderator can read what a report said without opening the report is that
    the internal channels get the detail and Discord does not.

Uses SQLite in memory, like `test_signup_gate.py`: the behaviour under test is
what gets written, and asserting on a mocked session would test the mock.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.database import Base  # noqa: E402
from src.models.alert_channel import AlertChannel  # noqa: E402
from src.models.notification import Notification  # noqa: E402
from src.models.staff_alert import StaffAlert  # noqa: E402
from src.models.user import User  # noqa: E402
from src.utils import channels  # noqa: E402


def message(**overrides):
    """A dispatched message, in the shape `alerting.dispatch` builds."""
    values = {
        'event': 'server.failed',
        'title': 'Server 2 gave up starting',
        'description': 'It wanted to be up and could not stay up.',
        'detail': 'crash loop: 5 attempts in 4 minutes',
        'fields': [('Server', 'Muldraugh')],
        'link': '/admin/servers/2',
        'server_id': 2,
        'color': 0xE74C3C,
    }
    values.update(overrides)
    return values


class StaffFeedTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()
        self.addCleanup(self.session.close)
        self.channel = AlertChannel(kind=AlertChannel.KIND_INAPP, name='Staff feed',
                                    events=['server.failed'], enabled=True)

    def staff(self, count):
        for n in range(count):
            self.session.add(User(username=f'mod{n}', email=f'm{n}@example.com',
                                  password_hash='x', role=User.ROLE_MODERATOR))
        self.session.flush()

    def deliver(self, **overrides):
        ok, error, _ = channels.deliver(self.session, self.channel, message(**overrides))
        self.session.flush()
        return ok, error


class TestOneRowNotOnePerModerator(StaffFeedTestCase):

    def test_one_alert_writes_one_row(self):
        self.staff(10)
        ok, error = self.deliver()
        self.assertTrue(ok, error)
        self.assertEqual(self.session.query(StaffAlert).count(), 1)

    def test_the_row_count_does_not_follow_the_staff_count(self):
        # The regression this split exists to prevent: ten moderators used to
        # mean ten rows per player join.
        self.staff(50)
        self.deliver()
        self.assertEqual(self.session.query(StaffAlert).count(), 1)

    def test_it_is_written_even_with_no_staff_at_all(self):
        # The old sender failed here ("there is nobody to notify"). The feed is
        # a place, not a mailing list: it exists whether or not anyone has been
        # appointed yet, and a deployment mid-setup should not lose its alerts.
        ok, error = self.deliver()
        self.assertTrue(ok, error)
        self.assertEqual(self.session.query(StaffAlert).count(), 1)


class TestNothingReachesThePlayerInbox(StaffFeedTestCase):

    def test_no_notifications_are_written(self):
        self.staff(3)
        self.deliver()
        self.assertEqual(self.session.query(Notification).count(), 0)


class TestWhatTheRowCarries(StaffFeedTestCase):

    def row(self, **overrides):
        self.deliver(**overrides)
        return self.session.query(StaffAlert).one()

    def test_the_event_key_is_kept(self):
        # The feed filters and renders by it.
        self.assertEqual(self.row().event, 'server.failed')

    def test_the_detail_is_included(self):
        # Internal channel: this is what a Discord copy deliberately lacks.
        self.assertIn('crash loop: 5 attempts', self.row().body)

    def test_the_description_and_fields_are_included(self):
        body = self.row().body
        self.assertIn('could not stay up', body)
        self.assertIn('Server: Muldraugh', body)

    def test_the_server_is_recorded(self):
        self.assertEqual(self.row().server_id, 2)

    def test_the_link_is_kept(self):
        self.assertEqual(self.row().link, '/admin/servers/2')

    def test_an_over_long_title_is_truncated_not_refused(self):
        # The column is 140; an alert with a long title should still arrive.
        self.assertEqual(len(self.row(title='x' * 400).title), 140)

    def test_a_message_with_nothing_below_the_title_has_no_body(self):
        row = self.row(description=None, detail=None, fields=[])
        self.assertIsNone(row.body)

    def test_an_unscoped_event_records_no_server(self):
        self.assertIsNone(self.row(event='user.signup', server_id=None).server_id)


class TestUnreadMarker(StaffFeedTestCase):
    """`users.staff_alerts_read_at` is the whole of "how far have I read"."""

    def unread_for(self, marker):
        query = self.session.query(StaffAlert)
        if marker is not None:
            query = query.filter(StaffAlert.created_at > marker)
        return query.count()

    def add(self, at):
        self.session.add(StaffAlert(event='user.signup', title='someone joined',
                                    created_at=at))
        self.session.flush()

    def test_never_opened_means_everything_is_unread(self):
        now = datetime.utcnow()
        self.add(now - timedelta(hours=2))
        self.add(now - timedelta(hours=1))
        self.assertEqual(self.unread_for(None), 2)

    def test_only_alerts_newer_than_the_marker_count(self):
        now = datetime.utcnow()
        self.add(now - timedelta(hours=2))
        marker = now - timedelta(hours=1)
        self.add(now)
        self.assertEqual(self.unread_for(marker), 1)

    def test_a_marker_after_everything_leaves_nothing_unread(self):
        now = datetime.utcnow()
        self.add(now - timedelta(hours=1))
        self.assertEqual(self.unread_for(now), 0)

    def test_the_marker_is_per_account(self):
        # One person reading the feed must not clear it for everybody else.
        self.staff(2)
        first, second = self.session.query(User).order_by(User.id).all()
        first.staff_alerts_read_at = datetime.utcnow()
        self.session.flush()
        self.assertIsNotNone(first.staff_alerts_read_at)
        self.assertIsNone(second.staff_alerts_read_at)


class TestRetention(StaffFeedTestCase):
    """`prune_staff_alerts` - the feed is operational, so it does not keep forever."""

    def prune(self, days):
        from unittest import mock
        from src.utils import jobs

        with mock.patch('src.utils.settings.get',
                        side_effect=lambda key: days if key == 'staff_alert_retention_days' else None):
            return jobs.REGISTRY['prune_staff_alerts']['run'](self.session)

    def add(self, age_days):
        self.session.add(StaffAlert(
            event='player.join', title='someone joined',
            created_at=datetime.utcnow() - timedelta(days=age_days)))
        self.session.flush()

    def test_entries_past_the_window_go(self):
        self.add(40)
        self.add(1)
        self.prune(30)
        self.assertEqual(self.session.query(StaffAlert).count(), 1)

    def test_zero_keeps_everything(self):
        self.add(400)
        result = self.prune(0)
        self.assertIn('indefinitely', result)
        self.assertEqual(self.session.query(StaffAlert).count(), 1)

    def test_it_says_what_it_did(self):
        # The result string is the only thing an operator sees on the Jobs page.
        self.add(40)
        self.assertIn('removed 1', self.prune(30))


if __name__ == '__main__':
    unittest.main()

"""Tests for the daily crate reminder: when it fires, and who it reaches.

The properties worth pinning:

  * **The window.** Nothing before the reminder time, one send inside it, and
    nothing hours later or past midnight - a reminder about a crate whose day
    is over is noise.
  * **Only the unclaimed.** A player who already collected today's crate, or a
    banned account, is never reminded.
  * **Once a day.** The job runs every few minutes; the day's mark is what
    keeps it to one send, and it fails closed.
  * **Dead subscriptions go.** A device the push service reports gone, or an
    endpoint the game-server refuses, is deleted; a temporary failure is kept.
  * **Only live sessions.** A subscription lives as long as the sign-in it was
    made in: refreshed with it, and never sent to - then deleted - once it has
    expired or was ended by a password change or "sign out everywhere".

SQLite in memory, like `test_events.py`: what is under test is what the
queries select.
"""
import os
import sys
import unittest
from datetime import date, datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.database import Base  # noqa: E402
from src.models.box import Box  # noqa: E402
from src.models.event import Event  # noqa: E402
from src.models.event_box import EventBox  # noqa: E402
from src.models.push_subscription import PushSubscription  # noqa: E402
from src.models.user import User  # noqa: E402
from src.models.user_box import UserBox  # noqa: E402
from src.utils import jobs, push  # noqa: E402

ATHENS = ZoneInfo('Europe/Athens')


class TestParseTime(unittest.TestCase):
    def test_accepts_24_hour_times(self):
        self.assertEqual(push.parse_time('18:00').hour, 18)
        self.assertEqual(push.parse_time(' 07:05 ').minute, 5)
        self.assertIsNotNone(push.parse_time('23:59'))

    def test_rejects_everything_else(self):
        for value in (None, '', '18', '6pm', '24:00', '18:60', '1:00', '18:00:00', 1800):
            self.assertIsNone(push.parse_time(value), msg=repr(value))
            self.assertIsNotNone(push.validate_time(value), msg=repr(value))


class TestWindow(unittest.TestCase):
    AT = push.parse_time('18:00')

    def at(self, hour, minute=0):
        return datetime(2026, 10, 4, hour, minute, tzinfo=ATHENS)

    def test_not_before_the_time(self):
        self.assertFalse(push.reminder_due(self.at(17, 59), self.AT))

    def test_inside_the_window(self):
        self.assertTrue(push.reminder_due(self.at(18, 0), self.AT))
        self.assertTrue(push.reminder_due(self.at(20, 30), self.AT))

    def test_not_hours_late(self):
        self.assertFalse(push.reminder_due(self.at(21, 0), self.AT))

    def test_never_past_midnight(self):
        late = push.parse_time('23:00')
        self.assertTrue(push.reminder_due(self.at(23, 30), late))
        self.assertFalse(push.reminder_due(datetime(2026, 10, 5, 0, 30, tzinfo=ATHENS), late))

    def test_ttl_ends_with_the_day(self):
        self.assertEqual(push.seconds_until_midnight(self.at(18, 0)), 6 * 3600)
        # Never zero: a push with no time to live is never delivered.
        self.assertEqual(push.seconds_until_midnight(
            datetime(2026, 10, 4, 23, 59, 59, tzinfo=ATHENS)), 60)


class PushDbTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()
        self.addCleanup(self.session.close)

    def user(self, name, role=User.ROLE_PLAYER):
        row = User(username=name, email=f'{name}@example.com', password_hash='x', role=role)
        self.session.add(row)
        self.session.flush()
        return row

    def subscribe(self, user, endpoint, expires_in=timedelta(days=1), token_version=0, sid='s1'):
        row = PushSubscription(user_id=user.id, endpoint=endpoint,
                               endpoint_hash=PushSubscription.hash_endpoint(endpoint),
                               session_id=sid, token_version=token_version,
                               session_expires_at=datetime.utcnow() + expires_in)
        self.session.add(row)
        self.session.flush()
        return row


class TestRecord(PushDbTestCase):
    def test_dead_go_working_are_stamped_failures_stay(self):
        alice = self.user('alice')
        for name in ('ok', 'gone', 'invalid', 'failed'):
            self.subscribe(alice, f'https://fcm.googleapis.com/{name}')

        sent, removed = push.record(self.session, {
            f'https://fcm.googleapis.com/{name}': name
            for name in ('ok', 'gone', 'invalid', 'failed')
        })

        self.assertEqual((sent, removed), (1, 2))
        left = {row.endpoint.rsplit('/', 1)[1]: row for row in self.session.query(PushSubscription)}
        self.assertEqual(set(left), {'ok', 'failed'})
        self.assertIsNotNone(left['ok'].last_sent_at)
        self.assertIsNone(left['failed'].last_sent_at)


class TestSessionBinding(PushDbTestCase):
    def test_bind_takes_the_tokens_session(self):
        row = PushSubscription(endpoint='https://fcm.googleapis.com/x', endpoint_hash='h')
        push.bind(row, {'sid': 'abc', 'exp': 1790000000, 'tv': 3, 'jti': 'j'})
        self.assertEqual(row.session_id, 'abc')
        self.assertEqual(row.session_expires_at, datetime.utcfromtimestamp(1790000000))
        self.assertEqual(row.token_version, 3)

    def test_bind_falls_back_to_jti_for_older_tokens(self):
        row = PushSubscription(endpoint='https://fcm.googleapis.com/x', endpoint_hash='h')
        push.bind(row, {'exp': 1790000000, 'jti': 'j'})
        self.assertEqual(row.session_id, 'j')
        self.assertEqual(row.token_version, 0)

    def test_extend_touches_only_that_session(self):
        alice = self.user('alice')
        mine = self.subscribe(alice, 'https://fcm.googleapis.com/mine', sid='mine')
        other = self.subscribe(alice, 'https://fcm.googleapis.com/other', sid='other')
        later = datetime(2030, 1, 1)
        self.assertEqual(push.extend_session(self.session, 'mine', later), 1)
        self.session.expire_all()
        self.assertEqual(mine.session_expires_at, later)
        self.assertNotEqual(other.session_expires_at, later)
        self.assertEqual(push.extend_session(self.session, None, later), 0)


class TestCrateReminderJob(PushDbTestCase):
    TODAY = date(2026, 10, 4)

    def setUp(self):
        super().setUp()
        box = Box(name='Daily crate', draws=1)
        self.session.add(box)
        self.session.flush()
        self.daily = Event(type=Event.TYPE_DAILY, name='Daily', enabled=True, system=True,
                           cadence=Event.CADENCE_DAILY)
        self.session.add(self.daily)
        self.session.flush()
        self.session.add(EventBox(event_id=self.daily.id, box_id=box.id, weight=1.0))
        self.box = box

        self.redis = mock.Mock()
        self.redis.set.return_value = True
        self.patch('src.utils.redis_utils.get_redis_connection', return_value=self.redis)
        self.settings = {'crate_reminder_time': '18:00'}
        mock_settings = mock.patch.object(jobs.settings, 'get', side_effect=self.settings.get)
        mock_settings.start()
        self.addCleanup(mock_settings.stop)
        tz = mock.patch.object(jobs.daily, 'primary_timezone', return_value=ATHENS)
        tz.start()
        self.addCleanup(tz.stop)
        self.now = datetime(2026, 10, 4, 18, 5, tzinfo=ATHENS)

    def patch(self, target, **kwargs):
        patcher = mock.patch(target, **kwargs)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_job(self):
        clock = mock.Mock(wraps=datetime)
        clock.now.return_value = self.now
        with mock.patch.object(jobs, 'datetime', clock):
            return jobs.crate_reminder(self.session)

    def claimed(self, user):
        self.session.add(UserBox(user_id=user.id, box_id=self.box.id, event_id=self.daily.id,
                                 source=UserBox.SOURCE_DAILY, period_key=self.TODAY.isoformat(),
                                 grant_date=self.TODAY))
        self.session.flush()

    def endpoints_reminded(self):
        result = self.run_job()
        self.assertIsInstance(result, tuple, msg=result)
        summary, deliver = result
        with mock.patch.object(push, 'send', return_value={}) as send, \
                mock.patch('src.database.db') as db:
            db.get_db.return_value.__enter__.return_value = self.session
            deliver()
        return sorted(send.call_args.args[0])

    def test_reminds_only_the_unclaimed_and_unbanned(self):
        waiting = self.user('waiting')
        done = self.user('done')
        banned = self.user('banned', role=User.ROLE_BANNED)
        self.user('nosub')
        self.subscribe(waiting, 'https://fcm.googleapis.com/phone')
        self.subscribe(waiting, 'https://updates.push.services.mozilla.com/desktop')
        self.subscribe(done, 'https://fcm.googleapis.com/done')
        self.subscribe(banned, 'https://fcm.googleapis.com/banned')
        self.claimed(done)

        self.assertEqual(self.endpoints_reminded(), [
            'https://fcm.googleapis.com/phone',
            'https://updates.push.services.mozilla.com/desktop',
        ])

    def test_a_claim_on_another_day_does_not_count(self):
        player = self.user('player')
        self.subscribe(player, 'https://fcm.googleapis.com/p')
        self.session.add(UserBox(user_id=player.id, box_id=self.box.id, event_id=self.daily.id,
                                 source=UserBox.SOURCE_DAILY, period_key='2026-10-03',
                                 grant_date=date(2026, 10, 3)))
        self.assertEqual(self.endpoints_reminded(), ['https://fcm.googleapis.com/p'])

    def test_expired_sessions_are_skipped_and_removed(self):
        player = self.user('player')
        self.subscribe(player, 'https://fcm.googleapis.com/live')
        self.subscribe(player, 'https://fcm.googleapis.com/lapsed', expires_in=timedelta(minutes=-1))
        self.assertEqual(self.endpoints_reminded(), ['https://fcm.googleapis.com/live'])
        self.assertEqual([r.endpoint for r in self.session.query(PushSubscription)],
                         ['https://fcm.googleapis.com/live'])

    def test_expired_sessions_are_removed_even_when_not_due(self):
        self.subscribe(self.user('p'), 'https://fcm.googleapis.com/lapsed',
                       expires_in=timedelta(minutes=-1))
        self.now = datetime(2026, 10, 4, 9, 0, tzinfo=ATHENS)
        self.assertIn('not due', self.run_job())
        self.assertEqual(self.session.query(PushSubscription).count(), 0)

    def test_sessions_ended_by_a_password_change_are_skipped_and_removed(self):
        player = self.user('player')
        player.token_version = 2
        self.subscribe(player, 'https://fcm.googleapis.com/current', token_version=2)
        self.subscribe(player, 'https://fcm.googleapis.com/before', token_version=1)
        self.assertEqual(self.endpoints_reminded(), ['https://fcm.googleapis.com/current'])
        self.assertEqual([r.endpoint for r in self.session.query(PushSubscription)],
                         ['https://fcm.googleapis.com/current'])

    def test_nothing_before_the_time(self):
        self.subscribe(self.user('p'), 'https://fcm.googleapis.com/p')
        self.now = datetime(2026, 10, 4, 17, 55, tzinfo=ATHENS)
        self.assertIn('not due', self.run_job())
        self.redis.set.assert_not_called()

    def test_once_a_day(self):
        self.subscribe(self.user('p'), 'https://fcm.googleapis.com/p')
        self.redis.set.return_value = None  # somebody already marked today
        self.assertIn('already sent', self.run_job())
        key = self.redis.set.call_args.args[0]
        self.assertIn('2026-10-04', key)

    def test_fails_closed_without_redis(self):
        self.subscribe(self.user('p'), 'https://fcm.googleapis.com/p')
        self.redis.set.side_effect = ConnectionError('down')
        self.assertIn('skipped', self.run_job())

    def test_no_daily_crate_no_reminder(self):
        self.subscribe(self.user('p'), 'https://fcm.googleapis.com/p')
        self.daily.enabled = False
        self.assertIn('no daily crate', self.run_job())

    def test_bad_time_is_skipped(self):
        self.settings['crate_reminder_time'] = 'six'
        self.assertIn('not a valid', self.run_job())


if __name__ == '__main__':
    unittest.main()

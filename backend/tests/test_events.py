"""Tests for which events grant a box, and which box each one picks.

Events replaced a fixed enum of box sizes, so the question "what is this player
owed right now" is now answered by rows rather than by code. These use SQLite in
memory for the same reason `test_signup_gate.py` does: the behaviour under test
is what the queries select, and asserting on hand-built Python objects would
test something else.

Covered here:

  * `grant_events` - the daily event plus every live custom one, and nothing
    else. The weekly bonus is deliberately absent; it is paid by a job keyed to
    a completed week, not pulled when somebody logs in.
  * `event_box_entries` / `pick_box_for_event` - a zero-weight box stays
    attached without ever being granted, and an event with nothing droppable
    picks nothing rather than granting an unopenable box.
  * `_period_key` - the value that makes a grant idempotent. Getting this wrong
    either pays a player twice or never pays them again.
"""
import os
import sys
import unittest
from datetime import date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.database import Base  # noqa: E402
from src.models.box import Box  # noqa: E402
from src.models.event import Event  # noqa: E402
from src.models.event_box import EventBox  # noqa: E402
from src.models.user_box import UserBox  # noqa: E402
from src.routes.boxes import _period_key  # noqa: E402
from src.utils import events  # noqa: E402


NOW = datetime(2026, 6, 15, 12, 0, 0)


class EventTestCase(unittest.TestCase):
    """A fresh in-memory database per test."""

    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()
        self.addCleanup(self.session.close)

    def box(self, name, draws=1):
        row = Box(name=name, draws=draws)
        self.session.add(row)
        self.session.flush()
        return row

    def event(self, type_, name=None, enabled=True, system=False,
              cadence=Event.CADENCE_DAILY, starts_at=None, ends_at=None):
        row = Event(type=type_, name=name or type_, enabled=enabled,
                    system=system, cadence=cadence,
                    starts_at=starts_at, ends_at=ends_at)
        self.session.add(row)
        self.session.flush()
        return row

    def attach(self, event, box, weight=1.0):
        row = EventBox(event_id=event.id, box_id=box.id, weight=weight)
        self.session.add(row)
        self.session.flush()
        return row


class TestGrantEvents(EventTestCase):
    """What a claim right now is owed."""

    def test_the_daily_event_is_granted(self):
        daily = self.event(Event.TYPE_DAILY, system=True)
        self.assertEqual([e.id for e in events.grant_events(self.session, NOW)],
                         [daily.id])

    def test_a_disabled_daily_event_grants_nothing(self):
        self.event(Event.TYPE_DAILY, system=True, enabled=False)
        self.assertEqual(events.grant_events(self.session, NOW), [])

    def test_the_weekly_bonus_is_never_granted_on_claim(self):
        # It is paid by the streak job against a completed week. Pulling it here
        # would hand out a bonus box to anyone who pressed the button.
        self.event(Event.TYPE_DAILY, system=True)
        self.event(Event.TYPE_WEEKLY_BONUS, system=True)
        types = [e.type for e in events.grant_events(self.session, NOW)]
        self.assertNotIn(Event.TYPE_WEEKLY_BONUS, types)

    def test_a_live_custom_event_stacks_on_top_of_the_daily(self):
        daily = self.event(Event.TYPE_DAILY, system=True)
        custom = self.event(Event.TYPE_CUSTOM, name='Launch Weekend',
                            starts_at=NOW - timedelta(days=1),
                            ends_at=NOW + timedelta(days=1))
        self.assertEqual([e.id for e in events.grant_events(self.session, NOW)],
                         [daily.id, custom.id])

    def test_a_custom_event_before_its_window_is_skipped(self):
        self.event(Event.TYPE_CUSTOM, starts_at=NOW + timedelta(days=1))
        self.assertEqual(events.grant_events(self.session, NOW), [])

    def test_a_custom_event_after_its_window_is_skipped(self):
        self.event(Event.TYPE_CUSTOM, ends_at=NOW - timedelta(days=1))
        self.assertEqual(events.grant_events(self.session, NOW), [])

    def test_a_custom_event_with_no_window_is_always_live(self):
        # Both ends blank means "open indefinitely", which is how a permanent
        # extra box is configured.
        custom = self.event(Event.TYPE_CUSTOM)
        self.assertEqual([e.id for e in events.grant_events(self.session, NOW)],
                         [custom.id])

    def test_a_disabled_custom_event_is_skipped_inside_its_window(self):
        self.event(Event.TYPE_CUSTOM, enabled=False,
                   starts_at=NOW - timedelta(days=1),
                   ends_at=NOW + timedelta(days=1))
        self.assertEqual(events.grant_events(self.session, NOW), [])

    def test_the_daily_event_comes_first(self):
        # The claim response surfaces the first box as "your box"; the daily one
        # is the one a player is looking for.
        self.event(Event.TYPE_CUSTOM, name='Custom')
        daily = self.event(Event.TYPE_DAILY, system=True)
        granted = events.grant_events(self.session, NOW)
        self.assertEqual(granted[0].id, daily.id)


class TestWeeklyBonusEnabled(EventTestCase):

    def test_it_is_off_when_the_event_does_not_exist(self):
        self.assertFalse(events.weekly_bonus_enabled(self.session))

    def test_it_follows_the_events_switch(self):
        bonus = self.event(Event.TYPE_WEEKLY_BONUS, system=True, enabled=False)
        self.assertFalse(events.weekly_bonus_enabled(self.session))
        bonus.enabled = True
        self.session.flush()
        self.assertTrue(events.weekly_bonus_enabled(self.session))


class TestEventBoxEntries(EventTestCase):
    """Which boxes an event can actually grant."""

    def test_attached_boxes_are_returned_with_their_weights(self):
        event = self.event(Event.TYPE_DAILY, system=True)
        small, big = self.box('Small'), self.box('Big', draws=3)
        self.attach(event, small, 3)
        self.attach(event, big, 1)
        self.assertEqual(sorted(events.event_box_entries(self.session, event.id)),
                         sorted([(small.id, 3.0), (big.id, 1.0)]))

    def test_a_zero_weight_box_is_attached_but_never_droppable(self):
        # Zero is how a box is taken out of rotation without losing the fact
        # that it belonged to this event.
        event = self.event(Event.TYPE_DAILY, system=True)
        self.attach(event, self.box('Retired'), 0)
        self.assertEqual(events.event_box_entries(self.session, event.id), [])

    def test_another_events_boxes_are_not_included(self):
        daily = self.event(Event.TYPE_DAILY, system=True)
        bonus = self.event(Event.TYPE_WEEKLY_BONUS, system=True)
        self.attach(bonus, self.box('Weekly Bonus', draws=4))
        self.assertEqual(events.event_box_entries(self.session, daily.id), [])


class TestPickBoxForEvent(EventTestCase):

    def test_an_event_with_nothing_droppable_picks_nothing(self):
        # The caller skips the grant on None. Granting a box that cannot be
        # opened is worse than granting none at all.
        event = self.event(Event.TYPE_DAILY, system=True)
        self.attach(event, self.box('Retired'), 0)
        self.assertIsNone(events.pick_box_for_event(self.session, event.id))

    def test_an_event_with_no_boxes_picks_nothing(self):
        event = self.event(Event.TYPE_DAILY, system=True)
        self.assertIsNone(events.pick_box_for_event(self.session, event.id))

    def test_the_only_droppable_box_is_always_the_one_picked(self):
        event = self.event(Event.TYPE_DAILY, system=True)
        self.attach(event, self.box('Retired'), 0)
        live = self.box('Small')
        self.attach(event, live, 1)
        for _ in range(20):
            self.assertEqual(events.pick_box_for_event(self.session, event.id),
                             live.id)


class TestPeriodKey(unittest.TestCase):
    """The value the (user, event, period) unique key is built from.

    A key that is too coarse pays a player once and never again; one that is too
    fine pays them repeatedly. Both are worth pinning.
    """

    def key(self, event, day=date(2026, 6, 15)):
        return _period_key(event, day)

    def test_the_daily_event_is_keyed_to_the_day(self):
        event = Event(type=Event.TYPE_DAILY, cadence=Event.CADENCE_DAILY)
        self.assertEqual(self.key(event), '2026-06-15')

    def test_a_daily_custom_event_is_also_keyed_to_the_day(self):
        event = Event(type=Event.TYPE_CUSTOM, cadence=Event.CADENCE_DAILY)
        self.assertEqual(self.key(event), '2026-06-15')

    def test_a_one_time_custom_event_is_keyed_to_a_constant(self):
        # So it can only ever be granted once for the whole window, however many
        # days the player claims across.
        event = Event(type=Event.TYPE_CUSTOM, cadence=Event.CADENCE_ONCE)
        self.assertEqual(self.key(event), UserBox.ONCE)
        self.assertEqual(self.key(event, date(2026, 7, 1)), UserBox.ONCE)

    def test_a_daily_event_keys_differ_across_days(self):
        event = Event(type=Event.TYPE_DAILY, cadence=Event.CADENCE_DAILY)
        self.assertNotEqual(self.key(event, date(2026, 6, 15)),
                            self.key(event, date(2026, 6, 16)))

    def test_the_once_cadence_only_applies_to_custom_events(self):
        # The daily system event ignores cadence weirdness rather than latching
        # itself to a single grant forever.
        event = Event(type=Event.TYPE_DAILY, cadence=Event.CADENCE_ONCE)
        self.assertEqual(self.key(event), '2026-06-15')


class TestGrantIdempotency(EventTestCase):
    """The unique key itself, which is what makes a repeat claim a no-op."""

    def _grant(self, user_id, event, box, period_key, day=date(2026, 6, 15)):
        self.session.add(UserBox(
            user_id=user_id, box_id=box.id, event_id=event.id,
            source=event.source, period_key=period_key, grant_date=day))
        self.session.flush()

    def test_the_same_event_and_period_cannot_be_granted_twice(self):
        from sqlalchemy.exc import IntegrityError
        event = self.event(Event.TYPE_DAILY, system=True)
        box = self.box('Small')
        self._grant(1, event, box, '2026-06-15')
        with self.assertRaises(IntegrityError):
            self._grant(1, event, box, '2026-06-15')

    def test_two_events_can_grant_in_the_same_period(self):
        # This is what lets a custom event stack on top of the daily box.
        daily = self.event(Event.TYPE_DAILY, system=True)
        custom = self.event(Event.TYPE_CUSTOM, name='Launch')
        box = self.box('Small')
        self._grant(1, daily, box, '2026-06-15')
        self._grant(1, custom, box, '2026-06-15')
        self.assertEqual(self.session.query(UserBox).count(), 2)

    def test_two_players_can_be_granted_the_same_event_and_period(self):
        event = self.event(Event.TYPE_DAILY, system=True)
        box = self.box('Small')
        self._grant(1, event, box, '2026-06-15')
        self._grant(2, event, box, '2026-06-15')
        self.assertEqual(self.session.query(UserBox).count(), 2)

    def test_a_lost_race_rolls_back_only_its_own_insert(self):
        """The savepoint in `claim_daily`, in the shape the route uses it.

        Two concurrent claims race on the unique key; the loser must cost only
        its own row. The trap is that `session.add()` outside the savepoint
        leaves the pending insert outside the SAVEPOINT's snapshot, so rolling
        back does not undo it - the session stays failed and the *commit* blows
        up, discarding every box granted before it. That failure only ever
        appears under concurrency, which is why it is pinned here.
        """
        from sqlalchemy.exc import IntegrityError

        daily = self.event(Event.TYPE_DAILY, system=True)
        custom = self.event(Event.TYPE_CUSTOM, name='Launch')
        box = self.box('Small')

        # First event grants normally.
        self._grant(1, daily, box, '2026-06-15')

        # Second event loses a race: the row is already there.
        self._grant(1, custom, box, '2026-06-15')
        self.session.commit()

        duplicate = UserBox(user_id=1, box_id=box.id, event_id=custom.id,
                            source=custom.source, period_key='2026-06-15',
                            grant_date=date(2026, 6, 15))
        try:
            with self.session.begin_nested():
                self.session.add(duplicate)
                self.session.flush()
            self.fail('the unique key should have refused the duplicate')
        except IntegrityError:
            pass

        # The session is still usable and the earlier grants survive - which is
        # the whole point of the savepoint.
        self.session.commit()
        self.assertEqual(self.session.query(UserBox).count(), 2)


if __name__ == '__main__':
    unittest.main()

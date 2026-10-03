"""Reading the box/event configuration during a grant.

Thin helpers over the models, always taking a caller-owned session. There is no
cache layer: a grant reads these once per player per day, and an open reads a
single box row, so the queries are cheap and always current.
"""
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

from src.models.box import Box
from src.models.event import Event
from src.models.event_box import EventBox
from src.models.notification import Notification
from src.models.user_box import UserBox
from src.utils import expiry, loot, notify


def system_event(session, event_type):
    """The single system event of a type (daily / weekly_bonus), or None."""
    return (session.query(Event)
            .filter(Event.type == event_type, Event.system.is_(True))
            .first())


def weekly_bonus_enabled(session):
    """Whether the weekly bonus event exists and is switched on."""
    event = system_event(session, Event.TYPE_WEEKLY_BONUS)
    return bool(event and event.enabled)


def grant_events(session, now=None):
    """Events that grant a box at claim time, daily first then live customs.

    The daily event when enabled, and every enabled custom event whose window
    currently includes ``now``. The weekly bonus is deliberately absent: it is
    earned by collecting daily boxes, not pulled on login - see
    `grant_weekly_bonus`.
    """
    now = now or datetime.utcnow()
    out = []

    daily = system_event(session, Event.TYPE_DAILY)
    if daily and daily.enabled:
        out.append(daily)

    customs = (session.query(Event)
               .filter(Event.type == Event.TYPE_CUSTOM, Event.enabled.is_(True))
               .order_by(Event.id)
               .all())
    out.extend(event for event in customs if event.is_live(now))
    return out


def event_box_entries(session, event_id):
    """``[(box_id, weight)]`` for an event, limited to droppable boxes.

    A box attached at weight 0 cannot be the one granted; set its weight above 0
    (or detach it) to take a box out of an event's rotation.
    """
    rows = (session.query(EventBox.box_id, EventBox.weight)
            .join(Box, Box.id == EventBox.box_id)
            .filter(EventBox.event_id == event_id,
                    EventBox.weight > 0)
            .all())
    return [(box_id, weight) for box_id, weight in rows]


def pick_box_for_event(session, event_id, rng=None):
    """Weighted-pick one box id for an event, or None if it has none in play."""
    entries = event_box_entries(session, event_id)
    if rng is None:
        return loot.pick_weighted(entries)
    return loot.pick_weighted(entries, rng)


def week_of(day):
    """``(monday, sunday)`` of the streak week containing ``day``.

    Monday to Sunday at the daily reset boundary. The bonus for a week is keyed
    to its Sunday, so every path that pays it agrees on what "already paid"
    means.
    """
    monday = day - timedelta(days=day.isoweekday() - 1)
    return monday, monday + timedelta(days=6)


def daily_days(session, user_id, day):
    """The distinct days of ``day``'s week on which the daily event granted a box."""
    monday, sunday = week_of(day)
    return [row[0] for row in
            (session.query(UserBox.grant_date)
             .filter(UserBox.user_id == user_id,
                     UserBox.source == UserBox.SOURCE_DAILY,
                     UserBox.grant_date >= monday,
                     UserBox.grant_date <= sunday)
             .distinct()
             .all())]


def grant_weekly_bonus(session, user_id, day, threshold):
    """Pay ``day``'s week bonus if it has been earned and not yet paid.

    Earned the moment the threshold-th daily box of the week is collected, so
    the claim that collects it calls this. ``>=`` rather than ``==`` so a
    lowered threshold, or a week that straddled the bonus being switched on,
    is paid on the next claim instead of never. The ``(user_id, event_id,
    period_key)`` key makes a repeat call a no-op. Returns the new box or None.
    """
    event = system_event(session, Event.TYPE_WEEKLY_BONUS)
    if not event or not event.enabled:
        return None

    days = daily_days(session, user_id, day)
    if len(days) < threshold:
        return None

    monday, sunday = week_of(day)
    period_key = sunday.isoformat()
    already = (session.query(UserBox.id)
               .filter_by(user_id=user_id, event_id=event.id, period_key=period_key)
               .first())
    if already:
        return None

    box_id = pick_box_for_event(session, event.id)
    if box_id is None:
        return None

    box = UserBox(user_id=user_id, box_id=box_id, event_id=event.id,
                  source=UserBox.SOURCE_BONUS, period_key=period_key,
                  grant_date=day, expires_at=expiry.box_deadline())
    try:
        # The same savepoint shape as `claim_daily`: a lost race costs only
        # this insert, not whatever the caller granted before it.
        with session.begin_nested():
            session.add(box)
            session.flush()
    except IntegrityError:
        return None

    notify.send(session, user_id, Notification.KIND_LOOT,
                'You earned a weekly bonus box',
                body=f'You collected {len(days)} daily boxes in the week of '
                     f'{monday:%d %b}. Your bonus is waiting to be opened.',
                link='/rewards')
    return box

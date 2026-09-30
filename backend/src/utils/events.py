"""Reading the box/event configuration during a grant.

Thin helpers over the models, always taking a caller-owned session. There is no
cache layer: a grant reads these once per player per day, and an open reads a
single box row, so the queries are cheap and always current.
"""
from datetime import datetime

from src.models.box import Box
from src.models.event import Event
from src.models.event_box import EventBox
from src.utils import loot


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
    paid by a job keyed to a completed week, not pulled on login.
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

"""Events: what causes a box to be granted, and which boxes are in play.

Three kinds:

* ``daily``         - the once-a-day grant. A single, system-owned event; it can
                      be enabled/disabled and its box line-up tuned, but not
                      created or deleted.
* ``weekly_bonus``  - the streak reward paid at the end of a week. Also a single
                      system event, gated by the same streak threshold as before.
* ``custom``        - operator-created and unlimited. Runs between ``starts_at``
                      and ``ends_at`` and grants either once for the whole window
                      (``once``) or every day inside it (``daily``).

An event does not *contain* loot directly. It points at one or more boxes with a
weight each (see :mod:`src.models.event_box`); a grant is a weighted pick of one
box. Custom events stack on top of the daily grant, so an active custom event
gives a player an extra box without displacing their daily one.
"""
from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
from src.database import Base


class Event(Base):
    """One box-granting event."""
    __tablename__ = 'events'

    TYPE_DAILY = 'daily'
    TYPE_WEEKLY_BONUS = 'weekly_bonus'
    TYPE_CUSTOM = 'custom'
    SYSTEM_TYPES = (TYPE_DAILY, TYPE_WEEKLY_BONUS)

    # How often a player can receive from this event.
    CADENCE_DAILY = 'daily'     # once per calendar day (daily event, custom-daily)
    CADENCE_WEEKLY = 'weekly'   # once per week-end (weekly bonus)
    CADENCE_ONCE = 'once'       # once for the whole window (custom one-time)

    # The `source` recorded on a granted box, kept short and stable for display
    # and for the streak query.
    _SOURCE = {TYPE_DAILY: 'daily', TYPE_WEEKLY_BONUS: 'bonus', TYPE_CUSTOM: 'custom'}

    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String(16), nullable=False, index=True)
    name = Column(String(80), nullable=False)
    description = Column(Text)
    enabled = Column(Boolean, nullable=False, default=True)
    cadence = Column(String(16), nullable=False, default=CADENCE_DAILY)
    # Only meaningful for custom events; the two system events ignore them.
    starts_at = Column(DateTime)
    ends_at = Column(DateTime)
    # System events (daily, weekly bonus) cannot be deleted and there is exactly
    # one of each.
    system = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def source(self):
        """The `source` token to stamp on boxes this event grants."""
        return self._SOURCE.get(self.type, self.type)

    def is_live(self, now=None):
        """Whether a custom event's window currently includes ``now``.

        The system events have no window, so they are always live when enabled.
        """
        if self.type != self.TYPE_CUSTOM:
            return True
        now = now or datetime.utcnow()
        if self.starts_at and now < self.starts_at:
            return False
        if self.ends_at and now > self.ends_at:
            return False
        return True

    def to_dict(self):
        return {
            'id': self.id,
            'type': self.type,
            'name': self.name,
            'description': self.description or '',
            'enabled': bool(self.enabled),
            'cadence': self.cadence,
            'starts_at': self.starts_at.isoformat() if self.starts_at else None,
            'ends_at': self.ends_at.isoformat() if self.ends_at else None,
            'system': bool(self.system),
        }

    def __repr__(self):
        return f"<Event(id={self.id}, type='{self.type}', name='{self.name}')>"

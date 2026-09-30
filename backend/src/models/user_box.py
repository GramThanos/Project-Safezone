"""User loot boxes: whatever an event has granted to an account."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, UniqueConstraint
from src.database import Base


class UserBox(Base):
    """A loot box granted to an account by an event.

    `period_key` is what makes a grant idempotent and prevents a player getting
    the same event's box twice in the same period. It is the calendar date for a
    daily grant, the week-ending date for the weekly bonus, and the constant
    ``'once'`` for a one-time custom event - so ``(user_id, event_id, period_key)``
    is unique and every grant path is safe to retry.

    `source` mirrors the granting event's type (`daily` / `bonus` / `custom`); it
    is denormalised here so the streak query and the player UI do not have to
    join back to the event, which may later be deleted.
    """
    __tablename__ = 'user_boxes'
    __table_args__ = (
        UniqueConstraint('user_id', 'event_id', 'period_key', name='uq_user_box_grant'),
    )

    STATUS_UNOPENED = 'unopened'
    STATUS_OPENED = 'opened'
    # Never opened in time. Kept rather than deleted so a player can see what
    # they let lapse, and so the record of what was granted stays intact.
    STATUS_EXPIRED = 'expired'
    # Taken away by staff. A status rather than a deleted row, because the row
    # is also the grant's idempotency guard: deleting it would let the player
    # claim the same event's box again for the same period.
    STATUS_REVOKED = 'revoked'

    SOURCE_DAILY = 'daily'
    SOURCE_BONUS = 'bonus'
    SOURCE_CUSTOM = 'custom'

    ONCE = 'once'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    box_id = Column(Integer, ForeignKey('boxes.id'), nullable=False, index=True)
    # Which event granted it. Null once that event has been deleted - the box a
    # player already holds outlives the event that produced it.
    event_id = Column(Integer, ForeignKey('events.id', ondelete='SET NULL'), index=True)
    source = Column(String(16), nullable=False, default=SOURCE_DAILY)
    period_key = Column(String(32), nullable=False)
    grant_date = Column(Date, nullable=False)
    # Null means it never expires, which is what a retention setting of 0 gives.
    expires_at = Column(DateTime)
    granted_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    opened_at = Column(DateTime)
    status = Column(String(16), nullable=False, default=STATUS_UNOPENED)

    def to_dict(self, box=None):
        data = {
            'id': self.id,
            'user_id': self.user_id,
            'box_id': self.box_id,
            'event_id': self.event_id,
            'source': self.source or self.SOURCE_DAILY,
            'grant_date': self.grant_date.isoformat() if self.grant_date else None,
            'granted_at': self.granted_at.isoformat() if self.granted_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'opened_at': self.opened_at.isoformat() if self.opened_at else None,
            'status': self.status,
        }
        if box is not None:
            data['box_name'] = box.name
            data['label'] = box.name
        return data

"""User loot boxes: the daily grant, and the weekly streak bonus."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, UniqueConstraint
from src.database import Base


class UserBox(Base):
    """A loot box granted to an account.

    `source` distinguishes the daily grant from the weekly streak bonus. It is
    part of the uniqueness rule because the bonus for a week is dated to the day
    that week ended - the same day the player also collected a daily box, which
    would otherwise collide.
    """
    __tablename__ = 'user_boxes'
    # One daily grant per account per day; one bonus per account per week-end.
    __table_args__ = (
        UniqueConstraint('user_id', 'grant_date', 'source', name='uq_user_box_grant'),
    )

    STATUS_UNOPENED = 'unopened'
    STATUS_OPENED = 'opened'
    # Never opened in time. Kept rather than deleted so a player can see what
    # they let lapse, and so the record of what was granted stays intact.
    STATUS_EXPIRED = 'expired'

    SOURCE_DAILY = 'daily'
    SOURCE_BONUS = 'bonus'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    size = Column(String(16), nullable=False)
    grant_date = Column(Date, nullable=False)
    source = Column(String(16), nullable=False, default=SOURCE_DAILY)
    # Null means it never expires, which is what a retention setting of 0 gives.
    expires_at = Column(DateTime)
    granted_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    opened_at = Column(DateTime)
    status = Column(String(16), nullable=False, default=STATUS_UNOPENED)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'size': self.size,
            'source': self.source or self.SOURCE_DAILY,
            'grant_date': self.grant_date.isoformat() if self.grant_date else None,
            'granted_at': self.granted_at.isoformat() if self.granted_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'opened_at': self.opened_at.isoformat() if self.opened_at else None,
            'status': self.status
        }

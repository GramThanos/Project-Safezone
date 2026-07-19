"""User loot box: granted once per day on login, opened to draw rewards."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, UniqueConstraint
from src.database import Base


class UserBox(Base):
    """A loot box granted to an account. One grant per account per day."""
    __tablename__ = 'user_boxes'
    # Enforces the once-per-day grant rule at the database level.
    __table_args__ = (UniqueConstraint('user_id', 'grant_date', name='uq_user_box_daily'),)

    STATUS_UNOPENED = 'unopened'
    STATUS_OPENED = 'opened'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    size = Column(String(16), nullable=False)
    grant_date = Column(Date, nullable=False)
    granted_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    opened_at = Column(DateTime)
    status = Column(String(16), nullable=False, default=STATUS_UNOPENED)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'size': self.size,
            'grant_date': self.grant_date.isoformat() if self.grant_date else None,
            'granted_at': self.granted_at.isoformat() if self.granted_at else None,
            'opened_at': self.opened_at.isoformat() if self.opened_at else None,
            'status': self.status
        }

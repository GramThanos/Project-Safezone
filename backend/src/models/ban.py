"""Ban records.

A table rather than columns on `users`, because the question a moderator
actually asks is "has this happened before?" - and a flag on the account can
only ever answer "is it happening now". History is the point.

The account's role still carries the live state; this records why, by whom, for
how long, and what to put back afterwards.
"""
from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from src.database import Base


class Ban(Base):
    """One ban, past or present."""
    __tablename__ = 'bans'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'),
                     nullable=False, index=True)
    issued_by = Column(Integer)  # staff user id; None = system
    reason = Column(Text)
    # Null means permanent. A timed ban is restored by the `expire_bans` job.
    expires_at = Column(DateTime, index=True)
    # What the account was before, so lifting the ban puts back the right role
    # rather than assuming everyone was a plain player.
    prior_role = Column(String(20))
    lifted_at = Column(DateTime)
    lifted_by = Column(Integer)  # None when lifted automatically on expiry
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def is_active(self):
        return self.lifted_at is None

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'issued_by': self.issued_by,
            'reason': self.reason,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'permanent': self.expires_at is None,
            'prior_role': self.prior_role,
            'lifted_at': self.lifted_at.isoformat() if self.lifted_at else None,
            'lifted_by': self.lifted_by,
            'active': self.is_active(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<Ban(user_id={self.user_id}, active={self.is_active()})>"

"""Invitation links.

A link can be single-use, time-limited, or both - the two are independent, so an
operator can hand out one permanent code for a trusted forum thread and a
one-shot link for a specific person.

Like `AuthToken`, only the hash of the code is stored: the plaintext exists in
the link that was handed out and nowhere else.
"""
import hashlib
import secrets
from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from src.database import Base


def hash_code(plaintext):
    """The stored form of an invitation code."""
    return hashlib.sha256(plaintext.encode('utf-8')).hexdigest()


class Invitation(Base):
    """An invitation code that permits one or more signups."""
    __tablename__ = 'invitations'

    id = Column(Integer, primary_key=True, autoincrement=True)
    code_hash = Column(String(64), nullable=False, unique=True, index=True)
    created_by = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'),
                        nullable=False, index=True)
    note = Column(Text)  # who it was meant for, so a stale code can be recognised
    max_uses = Column(Integer, nullable=False, default=1)
    uses = Column(Integer, nullable=False, default=0)
    expires_at = Column(DateTime)  # null = no expiry
    revoked_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    @classmethod
    def issue(cls, created_by, max_uses=1, expires_at=None, note=None):
        """Mint an invitation. Returns ``(row, plaintext_code)``."""
        plaintext = secrets.token_urlsafe(24)
        row = cls(
            code_hash=hash_code(plaintext),
            created_by=created_by,
            note=note,
            max_uses=max(1, int(max_uses or 1)),
            expires_at=expires_at
        )
        return row, plaintext

    def is_usable(self):
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None and self.expires_at <= datetime.utcnow():
            return False
        return (self.uses or 0) < (self.max_uses or 1)

    def status(self):
        """Why this invitation can or cannot be used, for the panel."""
        if self.revoked_at is not None:
            return 'revoked'
        if self.expires_at is not None and self.expires_at <= datetime.utcnow():
            return 'expired'
        if (self.uses or 0) >= (self.max_uses or 1):
            return 'used'
        return 'active'

    def to_dict(self):
        return {
            'id': self.id,
            'created_by': self.created_by,
            'note': self.note,
            'max_uses': self.max_uses,
            'uses': self.uses,
            'status': self.status(),
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<Invitation(id={self.id}, status='{self.status()}')>"

"""Single-use tokens for email verification and password reset.

Only the SHA-256 of the token is stored. A stolen database dump then yields
nothing usable: the plaintext exists solely in the email that was sent, exactly
like a password hash.
"""
import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from src.database import Base


def hash_token(plaintext):
    """The stored form of a token."""
    return hashlib.sha256(plaintext.encode('utf-8')).hexdigest()


class AuthToken(Base):
    """A one-time token tied to an account and a purpose."""
    __tablename__ = 'auth_tokens'

    PURPOSE_VERIFY = 'verify'
    PURPOSE_RESET = 'reset'
    PURPOSES = [PURPOSE_VERIFY, PURPOSE_RESET]

    # A verification link is a convenience; a reset link is a way into the
    # account, so it lives for a lot less time.
    LIFETIMES = {
        PURPOSE_VERIFY: timedelta(hours=24),
        PURPOSE_RESET: timedelta(hours=1),
    }

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'),
                     nullable=False, index=True)
    purpose = Column(String(16), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    @classmethod
    def issue(cls, user_id, purpose):
        """Mint a token. Returns ``(row, plaintext)`` - store the row, mail the text."""
        plaintext = secrets.token_urlsafe(32)
        row = cls(
            user_id=user_id,
            purpose=purpose,
            token_hash=hash_token(plaintext),
            expires_at=datetime.utcnow() + cls.LIFETIMES[purpose]
        )
        return row, plaintext

    def is_usable(self):
        return self.used_at is None and self.expires_at > datetime.utcnow()

    def __repr__(self):
        return f"<AuthToken(user_id={self.user_id}, purpose='{self.purpose}')>"

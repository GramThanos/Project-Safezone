"""Claim request model: an account claiming an in-game character.

An account submits a request to link an in-game character (in_game_username on a
server). The character must be online at request time. An admin then approves or
rejects it; on approval the character is linked to the account.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from src.database import Base


class ClaimRequest(Base):
    """A request from an account to link an in-game character to itself."""
    __tablename__ = 'claim_requests'

    # Claims are approved automatically on the online check - the proof is that
    # the requester controls a character that is connected right now. `pending`
    # and `rejected` remain only for rows created before that change.
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_REVOKED = 'revoked'
    STATUSES = [STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED, STATUS_REVOKED]

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    server_id = Column(Integer, nullable=False, index=True)
    in_game_username = Column(String(32), nullable=False, index=True)
    status = Column(String(16), nullable=False, default=STATUS_PENDING, index=True)
    character_id = Column(Integer)  # set when approved
    reviewed_by = Column(Integer)  # staff user id; None when approved automatically
    reason = Column(Text)  # why a link was revoked, shown to the player
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    reviewed_at = Column(DateTime)

    def __repr__(self):
        return (f"<ClaimRequest(id={self.id}, user_id={self.user_id}, "
                f"username='{self.in_game_username}', status='{self.status}')>")

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'server_id': self.server_id,
            'in_game_username': self.in_game_username,
            'status': self.status,
            'character_id': self.character_id,
            'reviewed_by': self.reviewed_by,
            'reason': self.reason,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None
        }

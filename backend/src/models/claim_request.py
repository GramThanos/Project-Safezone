"""Claim request model: an account claiming an in-game player.

An account submits a request to link an in-game player (in_game_username on a
server). The player must be online at request time. An admin then approves or
rejects it; on approval the player is linked to the account.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from src.database import Base


class ClaimRequest(Base):
    """A request from an account to link an in-game player to itself."""
    __tablename__ = 'claim_requests'

    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUSES = [STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED]

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    server_id = Column(Integer, nullable=False, index=True)
    in_game_username = Column(String(32), nullable=False, index=True)
    status = Column(String(16), nullable=False, default=STATUS_PENDING, index=True)
    player_id = Column(Integer)  # set when approved
    reviewed_by = Column(Integer)  # admin user id
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
            'player_id': self.player_id,
            'reviewed_by': self.reviewed_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None
        }

"""Audit log: a record of every privileged action, for accountability.

Covers role changes, server lifecycle and console commands, claim decisions,
reward and loot-pool edits, direct gives, character unlinks and deliveries.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from src.database import Base


class AuditLog(Base):
    """An audited action (claim review, reward delivery, etc.)."""
    __tablename__ = 'audit_logs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    actor_user_id = Column(Integer, index=True)  # who performed it (None = system)
    action = Column(String(48), nullable=False, index=True)
    target = Column(String(128))
    detail = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'actor_user_id': self.actor_user_id,
            'action': self.action,
            'target': self.target,
            'detail': self.detail,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

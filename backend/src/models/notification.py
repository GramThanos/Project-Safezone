"""In-app notifications.

Every asynchronous flow in this product used to end with the player refreshing a
page hopefully: a claim was approved, a delivery failed, a box was waiting, and
nothing said so. This is the one table that fixes all of them.

Kept deliberately plain. Polling a table is entirely adequate at this scale, and
adding a websocket layer to a stack that has none would be a lot of machinery for
a badge.
"""
from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index
from src.database import Base


class Notification(Base):
    """One message for one account."""
    __tablename__ = 'notifications'

    # Kinds exist so the UI can pick an icon and a person can mute a category
    # later; they are not a state machine.
    KIND_CLAIM = 'claim'
    KIND_DELIVERY = 'delivery'
    KIND_LOOT = 'loot'
    KIND_ACCOUNT = 'account'
    KIND_MODERATION = 'moderation'
    KINDS = [KIND_CLAIM, KIND_DELIVERY, KIND_LOOT, KIND_ACCOUNT, KIND_MODERATION]

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'),
                     nullable=False, index=True)
    kind = Column(String(16), nullable=False, default=KIND_ACCOUNT)
    title = Column(String(140), nullable=False)
    body = Column(Text)
    link = Column(String(255))  # where in the app this is about
    read_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # The inbox query is always "this user's, unread first, newest first".
    __table_args__ = (
        Index('ix_notifications_user_read', 'user_id', 'read_at', 'created_at'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'kind': self.kind,
            'title': self.title,
            'body': self.body,
            'link': self.link,
            'read': self.read_at is not None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<Notification(user_id={self.user_id}, kind='{self.kind}')>"

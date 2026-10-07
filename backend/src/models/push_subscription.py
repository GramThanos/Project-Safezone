"""Browser push subscriptions: how to reach one device of one account.

A row is created when a player switches reminders on in a browser, and removed
when they switch them off there, when the push service reports the device gone,
or with the account. One account can have several (a phone and a desktop); one
device has exactly one, so re-subscribing from a browser another account used
moves the row to the account signed in now.

It also belongs to the sign-in it was made in. `session_id` is the token's
`sid`, which survives refreshes; `session_expires_at` follows each refresh
(`push.extend_session`), and `token_version` is the account's at the time. A
subscription whose session has expired, or was ended by a password change or
"sign out everywhere", is never sent to and is deleted by the reminder job - so
a device nobody is signed in on stops getting reminders. The browser keeps its
side, and the next sign-in on that device binds it to the new session.

The endpoint is unique by its hash because MariaDB cannot index a TEXT column
whole, and endpoints are long (Windows' run to several hundred characters).
"""
import hashlib
from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint
from src.database import Base


class PushSubscription(Base):
    """One device's push subscription."""
    __tablename__ = 'push_subscriptions'
    __table_args__ = (
        UniqueConstraint('endpoint_hash', name='uq_push_subscriptions_endpoint_hash'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    endpoint_hash = Column(String(64), nullable=False)
    endpoint = Column(Text, nullable=False)
    # The browser's keys for an encrypted payload. Unused while pushes carry
    # none (see game-server/src/push.py), and kept so that adding one later does
    # not need every device to subscribe again.
    p256dh = Column(String(128))
    auth = Column(String(64))
    session_id = Column(String(64), index=True)
    session_expires_at = Column(DateTime)
    token_version = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_sent_at = Column(DateTime)

    @staticmethod
    def hash_endpoint(endpoint):
        return hashlib.sha256(endpoint.encode('utf-8')).hexdigest()

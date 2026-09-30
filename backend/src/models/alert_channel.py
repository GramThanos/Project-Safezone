"""Where staff alerts go.

One row is one destination - a Discord webhook, the staff feed, an ops mailbox
- with the list of events it wants to hear about. Three kinds in one table
rather than three tables, because everything except the sending is identical:
they all subscribe to the same catalog, filter by the same servers, and fail in
the same ways. A fourth kind should be a row, not a schema change.

`target` is what the kind needs to reach its destination: a webhook URL, one or
more email addresses, nothing at all for the inbox. A webhook URL is a **bearer
secret** - anyone holding it can post into that channel - so it is never
returned to the browser whole; `masked_target()` is what the panel sees, and
replacing it means typing a new one. Email addresses are not secret and come
back in full, because an operator has to be able to see and edit the list.
"""
from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, JSON
from src.database import Base


class AlertChannel(Base):
    """One alert destination and its subscriptions."""
    __tablename__ = 'alert_channels'

    KIND_WEBHOOK = 'webhook'
    KIND_INAPP = 'inapp'
    KIND_EMAIL = 'email'
    KINDS = [KIND_WEBHOOK, KIND_INAPP, KIND_EMAIL]

    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(16), nullable=False, default=KIND_WEBHOOK)
    name = Column(String(64), nullable=False)   # which channel this is, for the panel
    target = Column(Text)                       # URL, addresses, or nothing
    # Event keys from `src/utils/alerting.py::EVENTS`. Unknown keys are simply
    # never matched, so an event kind removed from the code degrades to silence
    # rather than an error on a row nobody has looked at in a year.
    events = Column(JSON, nullable=False, default=list)
    # Server ids this channel cares about; empty/null means every server. Only
    # consulted for events that happen *on* a server.
    server_ids = Column(JSON)
    enabled = Column(Boolean, nullable=False, default=True)

    created_by = Column(Integer)  # user id, for the audit trail
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow,
                        nullable=False)

    # What happened last time we tried. The panel shows this because a channel
    # that stopped working is otherwise indistinguishable from a quiet one.
    last_sent_at = Column(DateTime)
    last_status = Column(String(16))   # 'ok' | 'failed'
    last_error = Column(Text)
    # Consecutive failures. Reset on success; a destination that is gone for
    # good is switched off rather than retried forever (see `alerting.py`).
    failure_count = Column(Integer, nullable=False, default=0)

    def masked_target(self):
        """The destination as the panel may see it.

        For a webhook, everything up to the token:
        `https://discord.com/api/webhooks/<id>/<token>` keeps the id - enough to
        tell two webhooks apart, useless to anyone who copies it out of a
        screenshot.
        """
        if self.kind != self.KIND_WEBHOOK:
            return self.target or ''
        url = self.target or ''
        head, _, token = url.rpartition('/')
        if not head or not token:
            return url
        return f"{head}/{'•' * 8}{token[-4:] if len(token) > 8 else ''}"

    def wants(self, event, server_id=None):
        """Whether this channel should be told about one event."""
        if not self.enabled:
            return False
        if event not in (self.events or []):
            return False
        # An empty filter means every server. A server-scoped event from a
        # server this row does not list is not its business.
        wanted = self.server_ids or []
        if wanted and server_id is not None:
            try:
                return int(server_id) in [int(s) for s in wanted]
            except (TypeError, ValueError):
                return False
        return True

    def to_dict(self):
        return {
            'id': self.id,
            'kind': self.kind,
            'name': self.name,
            'target': self.masked_target(),
            'events': self.events or [],
            'server_ids': self.server_ids or [],
            'enabled': bool(self.enabled),
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_sent_at': self.last_sent_at.isoformat() if self.last_sent_at else None,
            'last_status': self.last_status,
            'last_error': self.last_error,
            'failure_count': self.failure_count or 0,
        }

    def __repr__(self):
        return f"<AlertChannel(id={self.id}, kind='{self.kind}', name='{self.name}')>"

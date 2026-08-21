"""Player reports and ban appeals.

Two shapes of the same thing: somebody outside the staff raising an issue that
needs a human decision. Moderation was entirely staff-initiated until now, which
meant a griefed player had nowhere to go and a banned one had no way to answer.

Modelled closely on the claim flow - submit, review, resolve with a reason -
because that flow already works and players already understand it.
"""
from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index
from src.database import Base


class Report(Base):
    """One report or appeal."""
    __tablename__ = 'reports'

    KIND_REPORT = 'report'
    KIND_APPEAL = 'appeal'
    KINDS = [KIND_REPORT, KIND_APPEAL]

    STATUS_OPEN = 'open'
    STATUS_RESOLVED = 'resolved'    # acted on
    STATUS_DISMISSED = 'dismissed'  # looked at, nothing to do
    STATUSES = [STATUS_OPEN, STATUS_RESOLVED, STATUS_DISMISSED]

    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(16), nullable=False, default=KIND_REPORT, index=True)
    reporter_user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'),
                              nullable=False, index=True)

    # Who or what it is about. An in-game name is free text on purpose: the
    # person being reported may have no account here at all.
    subject_username = Column(String(64))
    server_id = Column(Integer)

    body = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, default=STATUS_OPEN, index=True)

    # The staff answer, which the reporter sees. A resolution nobody explains is
    # indistinguishable from being ignored.
    resolution = Column(Text)
    reviewed_by = Column(Integer)
    reviewed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # The moderator queue is always "open first, oldest first".
    __table_args__ = (
        Index('ix_reports_status_created', 'status', 'created_at'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'kind': self.kind,
            'reporter_user_id': self.reporter_user_id,
            'subject_username': self.subject_username,
            'server_id': self.server_id,
            'body': self.body,
            'status': self.status,
            'resolution': self.resolution,
            'reviewed_by': self.reviewed_by,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<Report(id={self.id}, kind='{self.kind}', status='{self.status}')>"

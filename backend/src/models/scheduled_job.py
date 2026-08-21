"""Recurring jobs.

Everything the stack does on a schedule lives in one table, so an operator can
see what runs, when it last ran, and what happened - rather than the behaviour
being scattered across sleep loops in three services.
"""
from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, JSON
from src.database import Base


class ScheduledJob(Base):
    """One recurring job."""
    __tablename__ = 'scheduled_jobs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Which handler runs (see src/utils/jobs.py). Unique so a job cannot be
    # accidentally registered twice and run twice.
    kind = Column(String(48), nullable=False, unique=True, index=True)
    interval_seconds = Column(Integer, nullable=False, default=3600)
    params = Column(JSON)
    enabled = Column(Boolean, nullable=False, default=True)

    next_run_at = Column(DateTime, index=True)
    last_run_at = Column(DateTime)
    last_result = Column(Text)
    # Set while a worker holds the job, cleared when it finishes. A job left
    # with this set was abandoned by a restart, and is reclaimed after
    # STALE_AFTER rather than blocking forever.
    running_since = Column(DateTime)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'kind': self.kind,
            'interval_seconds': self.interval_seconds,
            'params': self.params or {},
            'enabled': bool(self.enabled),
            'next_run_at': self.next_run_at.isoformat() if self.next_run_at else None,
            'last_run_at': self.last_run_at.isoformat() if self.last_run_at else None,
            'last_result': self.last_result,
            'running': self.running_since is not None,
        }

    def __repr__(self):
        return f"<ScheduledJob(kind='{self.kind}', enabled={self.enabled})>"

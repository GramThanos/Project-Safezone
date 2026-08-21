"""Runtime-editable settings.

Everything else in the stack is an environment variable read at startup, which
means every operational change is a redeploy. That is the wrong shape for the
handful of settings an operator reaches for *during* an incident - closing
registration, say. A row here overrides the environment default for exactly
those keys; see `src/utils/settings.py` for the registry of which they are.
"""
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Integer
from src.database import Base


class AppSetting(Base):
    """One overridden setting. Absent row = use the environment default."""
    __tablename__ = 'app_settings'

    key = Column(String(64), primary_key=True)
    value = Column(Text)  # always stored as text; the registry knows the type
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow,
                        nullable=False)
    updated_by = Column(Integer)  # user id, for the audit trail

    def __repr__(self):
        return f"<AppSetting(key='{self.key}')>"

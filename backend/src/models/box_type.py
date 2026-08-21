"""Loot box types: how likely each size is, and how much it gives.

These were hardcoded. They are the two numbers an operator wants to adjust as a
season goes on, so they belong in a table an admin can edit rather than in a
constant that needs a redeploy.

`src/utils/loot.py` still holds the defaults - they seed this table and act as
the fallback if it cannot be read.
"""
from datetime import datetime

from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from src.database import Base


class BoxType(Base):
    """One box size."""
    __tablename__ = 'box_types'

    size = Column(String(16), primary_key=True)
    label = Column(String(48))
    # Rewards drawn when the box is opened.
    draws = Column(Integer, nullable=False, default=1)
    # Relative chance of this size on the daily roll. Zero means "never rolled" -
    # which is how the weekly bonus box exists without being obtainable daily.
    weight = Column(Float, nullable=False, default=0.0)
    active = Column(Boolean, nullable=False, default=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'size': self.size,
            'label': self.label or self.size.title(),
            'draws': self.draws,
            'weight': self.weight,
            'active': bool(self.active),
        }

    def __repr__(self):
        return f"<BoxType(size='{self.size}', weight={self.weight})>"

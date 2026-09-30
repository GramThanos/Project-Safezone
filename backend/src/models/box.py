"""Loot boxes: an admin-authored box with a name, a description and a loot pool.

Boxes used to be a fixed enum of sizes (small/medium/big/bonus) baked into the
code. They are now records an operator creates and names, so a season can add a
"Halloween crate" without a redeploy. Which box a player actually receives is
decided by an *event* (see :mod:`src.models.event`); a box on its own is just a
named loot pool with a draw count.
"""
from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime
from src.database import Base


class Box(Base):
    """One named box: how much it gives, and (via `box_loot_pools`) what."""
    __tablename__ = 'boxes'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False, unique=True)
    description = Column(Text)
    # Rewards drawn when the box is opened.
    draws = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description or '',
            'draws': self.draws,
        }

    def __repr__(self):
        return f"<Box(id={self.id}, name='{self.name}')>"

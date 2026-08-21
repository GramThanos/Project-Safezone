"""Reward catalog model (items and usables).

A unified table keeps delivery uniform: items carry an ``in_game_id`` delivered via
`additem`; usables carry an ``action_id`` from the game-server's action catalog
plus its ``action_params`` (e.g. ``teleport_to_beacon`` with a destination). The
admin UI presents them as two lists.

Every usable is a catalog action. The free-text command field that predated the
catalog has been removed, so there is no longer any way to reach the game console
with a string the catalog did not produce.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, JSON
from src.database import Base


class Reward(Base):
    """A grantable reward: an in-game item or a command-based usable."""
    __tablename__ = 'rewards'

    KIND_ITEM = 'item'
    KIND_USABLE = 'usable'
    KINDS = [KIND_ITEM, KIND_USABLE]

    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(16), nullable=False, default=KIND_ITEM, index=True)
    name = Column(String(128), nullable=False)
    description = Column(Text)
    icon = Column(String(512))
    in_game_id = Column(String(64))        # for items (e.g. "Base.Axe")
    count = Column(Integer, nullable=False, default=1)  # how many, for items
    action_id = Column(String(64))         # for usables: game-server action catalog id
    action_params = Column(JSON)           # for usables: validated action parameters
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<Reward(id={self.id}, kind='{self.kind}', name='{self.name}')>"

    def to_dict(self):
        return {
            'id': self.id,
            'kind': self.kind,
            'name': self.name,
            'description': self.description,
            'icon': self.icon,
            'in_game_id': self.in_game_id,
            'count': self.count if self.count is not None else 1,
            'action_id': self.action_id,
            'action_params': self.action_params or {},
            'active': self.active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

"""Reward catalog model (items and usables).

A unified table keeps delivery uniform: items carry an ``in_game_id`` delivered via
`additem`; usables carry a ``command_template`` (may reference ``{username}``)
delivered as a raw console command. The admin UI presents them as two lists.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
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
    command_template = Column(Text)        # for usables (may contain {username})
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
            'command_template': self.command_template,
            'active': self.active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

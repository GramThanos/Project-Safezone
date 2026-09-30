"""Reward catalog model (items and usables).

A unified table keeps delivery uniform: items carry an ``in_game_id`` delivered via
`additem`; usables carry a free-text ``commands`` block - one or more console
commands (optionally interleaved with executor-side ``sleep``/``wait`` steps),
with a ``{{USERNAME}}`` placeholder for the recipient. The admin UI presents the
two kinds as separate lists.

How *many* of an item drops is not a property of the reward: it lives on the
box's loot pool entry (see :class:`~src.models.box_loot_pool.BoxLootPool`), so
the same item can drop in different quantities from different boxes. The quantity
is captured onto the inventory item when the box is opened.

Command text is admin-authored and trusted; the game-server is still the command
boundary, validating the sequence when a reward is saved (via its reward preview
endpoint) and re-validating the one player-influenced value - the recipient's
in-game name - before it reaches the console at delivery time.

``action_id`` / ``action_params`` are the legacy catalog columns, retained so a
reward authored before free-text commands still reads and delivers; new usables
use ``commands``.
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
    commands = Column(Text)                # for usables: free-text command sequence
    action_id = Column(String(64))         # legacy usables: game-server action catalog id
    action_params = Column(JSON)           # legacy usables: validated action parameters
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
            'commands': self.commands,
            'action_id': self.action_id,
            'action_params': self.action_params or {},
            'active': self.active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

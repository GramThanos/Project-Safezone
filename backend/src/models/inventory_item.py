"""Inventory item: a reward an account owns, awaiting delivery to a player."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from src.database import Base


class InventoryItem(Base):
    """A won/granted reward held in an account's inventory until sent in-game."""
    __tablename__ = 'inventory_items'

    STATUS_HELD = 'held'          # owned, not yet sent
    STATUS_SENDING = 'sending'    # delivery task dispatched
    STATUS_DELIVERED = 'delivered'
    STATUS_FAILED = 'failed'

    SOURCE_BOX = 'box'
    SOURCE_ADMIN = 'admin'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    reward_id = Column(Integer, ForeignKey('rewards.id', ondelete='CASCADE'), nullable=False, index=True)
    source = Column(String(16), nullable=False, default=SOURCE_BOX)
    source_box_id = Column(Integer)
    status = Column(String(16), nullable=False, default=STATUS_HELD, index=True)
    player_id = Column(Integer)   # delivery target once sent
    task_id = Column(Integer)     # game-server delivery task id
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    delivered_at = Column(DateTime)

    def to_dict(self, reward=None):
        data = {
            'id': self.id,
            'user_id': self.user_id,
            'reward_id': self.reward_id,
            'source': self.source,
            'status': self.status,
            'player_id': self.player_id,
            'task_id': self.task_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'delivered_at': self.delivered_at.isoformat() if self.delivered_at else None
        }
        if reward is not None:
            data['reward'] = reward.to_dict()
        return data

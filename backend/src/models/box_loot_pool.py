"""Box loot pool: which rewards each box size can contain (admin-configured)."""
from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from src.database import Base


class BoxLootPool(Base):
    """A reward eligible to drop from a given box size."""
    __tablename__ = 'box_loot_pools'
    __table_args__ = (UniqueConstraint('size', 'reward_id', name='uq_box_pool'),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    size = Column(String(16), nullable=False, index=True)  # small/medium/big
    reward_id = Column(Integer, ForeignKey('rewards.id', ondelete='CASCADE'), nullable=False, index=True)

    def to_dict(self):
        return {'id': self.id, 'size': self.size, 'reward_id': self.reward_id}

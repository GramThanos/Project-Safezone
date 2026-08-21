"""Box loot pool: which rewards each box size can contain (admin-configured)."""
from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint, Float
from src.database import Base


class BoxLootPool(Base):
    """A reward eligible to drop from a given box size."""
    __tablename__ = 'box_loot_pools'
    __table_args__ = (UniqueConstraint('size', 'reward_id', name='uq_box_pool'),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    size = Column(String(16), nullable=False, index=True)  # small/medium/big
    reward_id = Column(Integer, ForeignKey('rewards.id', ondelete='CASCADE'), nullable=False, index=True)
    # Relative chance within this pool, not a percentage: 10 is ten times as
    # likely as 1. Zero keeps a reward in the pool but stops it dropping, which
    # retires it without deleting the history of who won it.
    weight = Column(Float, nullable=False, default=1.0)

    def to_dict(self):
        return {'id': self.id, 'size': self.size, 'reward_id': self.reward_id,
                'weight': self.weight}

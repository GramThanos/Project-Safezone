"""Box loot pool: which rewards each box can contain (admin-configured)."""
from sqlalchemy import Column, Integer, ForeignKey, UniqueConstraint, Float
from src.database import Base


class BoxLootPool(Base):
    """A reward eligible to drop from a given box."""
    __tablename__ = 'box_loot_pools'
    __table_args__ = (UniqueConstraint('box_id', 'reward_id', name='uq_box_pool'),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    box_id = Column(Integer, ForeignKey('boxes.id', ondelete='CASCADE'), nullable=False, index=True)
    reward_id = Column(Integer, ForeignKey('rewards.id', ondelete='CASCADE'), nullable=False, index=True)
    # Relative chance within this pool, not a percentage: 10 is ten times as
    # likely as 1. Zero keeps a reward in the pool but stops it dropping, which
    # retires it without deleting the history of who won it.
    weight = Column(Float, nullable=False, default=1.0)
    # How many of an item reward drops when this entry is picked. Lives here, not
    # on the reward, so the same item can drop in different quantities from
    # different boxes. Ignored for usable rewards (a command runs once).
    count = Column(Integer, nullable=False, default=1)

    def to_dict(self):
        return {'id': self.id, 'box_id': self.box_id, 'reward_id': self.reward_id,
                'weight': self.weight, 'count': self.count if self.count is not None else 1}

"""Shop listing: a catalog reward offered for coins (admin-configured).

A listing is a reward, how many of it one purchase gives, and the price. It can
sit in any number of categories (`shop_item_categories`) - a bandage can be both
"Medical" and "Starter kit" - and appears in the shop once it is in at least one
category that is shown.

The price is stored, not derived: the admin panel suggests 20 times the reward's
sell value as a starting point, and the admin decides. What is enforced is the
floor - never below what the reward sells back for (`coins.min_price`) - checked
when a listing is saved and again when a reward's value is raised, so buying and
selling back can never make coins.

A purchase becomes an ordinary inventory item (source ``shop``) and is delivered
the way every other reward is.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, Boolean, DateTime, ForeignKey
from src.database import Base


class ShopItem(Base):
    """One reward for sale."""
    __tablename__ = 'shop_items'

    id = Column(Integer, primary_key=True, autoincrement=True)
    reward_id = Column(Integer, ForeignKey('rewards.id', ondelete='CASCADE'),
                       nullable=False, index=True)
    # How many of the item one purchase gives. Always 1 for a usable, which
    # runs once per holding.
    count = Column(Integer, nullable=False, default=1)
    price = Column(Integer, nullable=False)
    # How many times one account may buy this a day (the primary server's
    # day, as for the daily crate). Null means no limit.
    daily_limit = Column(Integer)
    sort_order = Column(Integer, nullable=False, default=0)
    active = Column(Boolean, nullable=False, default=True)
    # Times bought, all told. Kept here rather than counted from
    # `shop_purchases`, which is pruned.
    sold = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self, reward=None, category_ids=None):
        data = {
            'id': self.id,
            'reward_id': self.reward_id,
            'count': self.count or 1,
            'price': self.price,
            'daily_limit': self.daily_limit,
            'sort_order': self.sort_order or 0,
            'active': bool(self.active),
            'sold': self.sold or 0,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        if reward is not None:
            data['reward'] = reward.to_dict()
        if category_ids is not None:
            data['category_ids'] = sorted(category_ids)
        return data

    def __repr__(self):
        return f"<ShopItem(id={self.id}, reward_id={self.reward_id}, price={self.price})>"

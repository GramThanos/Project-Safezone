"""Shop purchase: one listing bought by one account, kept to enforce daily limits.

A purchase's inventory item can be sent, sold or cleared away, so the item is no
record that a purchase happened; this is. It is what a listing's `daily_limit` is
counted against, and what staff can read to see who bought what.

Pruned with the coin log (`prune_coin_log`); a limit only ever reads today, and
the all-time count lives on the listing (`shop_items.sold`).
"""
from datetime import datetime
from sqlalchemy import Column, Integer, DateTime, ForeignKey, Index
from src.database import Base


class ShopPurchase(Base):
    """One purchase."""
    __tablename__ = 'shop_purchases'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    # Not foreign keys: a listing or a reward can be deleted, and what was
    # bought stays bought.
    shop_item_id = Column(Integer, nullable=False)
    reward_id = Column(Integer, nullable=False)
    count = Column(Integer, nullable=False, default=1)
    price = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # The limit check: this account, this listing, since the start of today.
    __table_args__ = (
        Index('ix_shop_purchases_user_item_created', 'user_id', 'shop_item_id', 'created_at'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'shop_item_id': self.shop_item_id,
            'reward_id': self.reward_id,
            'count': self.count,
            'price': self.price,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

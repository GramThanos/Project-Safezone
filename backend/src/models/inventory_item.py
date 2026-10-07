"""Inventory item: a reward an account owns, awaiting delivery to a character."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from src.database import Base


class InventoryItem(Base):
    """A won/granted reward held in an account's inventory until sent in-game."""
    __tablename__ = 'inventory_items'

    STATUS_HELD = 'held'          # owned, not yet sent
    STATUS_SENDING = 'sending'    # delivery task dispatched
    STATUS_DELIVERED = 'delivered'
    STATUS_EXPIRED = 'expired'    # held too long without being sent
    STATUS_FAILED = 'failed'

    SOURCE_BOX = 'box'
    SOURCE_ADMIN = 'admin'
    SOURCE_SHOP = 'shop'

    # What may still be sold back for coins: it is in the player's hands, not
    # on its way into the game and not already there.
    SELLABLE = (STATUS_HELD, STATUS_FAILED)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    reward_id = Column(Integer, ForeignKey('rewards.id', ondelete='CASCADE'), nullable=False, index=True)
    # How many of the item this holding delivers. Captured from the box's loot
    # pool entry when the box is opened, because the quantity lives on the pool
    # (not the reward) and the entry may change afterwards. 1 for usables.
    count = Column(Integer, nullable=False, default=1)
    source = Column(String(16), nullable=False, default=SOURCE_BOX)
    source_box_id = Column(Integer)
    status = Column(String(16), nullable=False, default=STATUS_HELD, index=True)
    character_id = Column(Integer)   # delivery target once sent
    task_id = Column(Integer)     # game-server delivery task id
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime)    # null = never expires
    sent_at = Column(DateTime)       # when delivery was dispatched (staleness clock)
    delivered_at = Column(DateTime)
    # Whether this holding still carries its reward's sell value. A reward is
    # worth its coin value once, however many items it holds, so when a send
    # splits a holding the value stays with the part left behind and the part
    # sent loses it - otherwise a split whose delivery failed and came back
    # would be two holdings to sell instead of one.
    sellable = Column(Boolean, nullable=False, default=True)

    def sell_value(self, reward, now=None):
        """Coins this holding sells back for right now; 0 if it cannot be sold.

        The reward's coin value, once: a holding of fifty nails is one reward.
        """
        if reward is None or self.status not in self.SELLABLE or self.sellable is False:
            return 0
        if self.expires_at is not None and self.expires_at <= (now or datetime.utcnow()):
            return 0
        return max(reward.coin_value or 0, 0)

    def to_dict(self, reward=None):
        data = {
            'id': self.id,
            'user_id': self.user_id,
            'reward_id': self.reward_id,
            'count': self.count if self.count is not None else 1,
            'source': self.source,
            'status': self.status,
            'character_id': self.character_id,
            'task_id': self.task_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            # Sent so the player can be warned before a reward is lost. Boxes
            # showed their deadline and items did not, which made expiry
            # something you discovered afterwards.
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'delivered_at': self.delivered_at.isoformat() if self.delivered_at else None
        }
        if reward is not None:
            data['reward'] = reward.to_dict()
            # Worked out here rather than in the browser, so what the discard
            # dialog promises is exactly what the server will pay.
            data['sell_value'] = self.sell_value(reward)
        return data

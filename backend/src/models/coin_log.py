"""Coin log: every coin an account gains, and where it came from.

Only gains. Spending is a purchase or a staff correction, both of which are in
the audit log already; this is the record of where coins enter the economy, so
it is one table whatever the source - a sale, zombie kills, a staff grant, and
any source added later. It is what the daily "yesterday you earned" summary is
built from and what staff read on an account's manage page.

History, not state: `prune_coin_log` trims it to `coin_log_retention_days`, and
nothing reads a total from it - running totals live on the rows they describe
(`characters.coin_earned`, the balance itself).
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from src.database import Base


class CoinLog(Base):
    """One gain of coins by one account."""
    __tablename__ = 'coin_log'

    # Sources that are not an earning source of a character (those are named
    # after their key in `coins.SOURCES`, such as ``kills``).
    SOURCE_SALE = 'sale'
    SOURCE_ADMIN = 'admin'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    amount = Column(Integer, nullable=False)
    source = Column(String(16), nullable=False)
    # How much of the source this paid for - kills, rewards sold - so a summary
    # can say "for 300 zombie kills" rather than only a number of coins.
    quantity = Column(Integer)
    # The character that earned it. Not a foreign key: an unlinked character's
    # row is deleted, and what it earned stays earned.
    character_id = Column(Integer)
    detail = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Read as "this account's, newest first" and "everyone's, for one day".
    __table_args__ = (
        Index('ix_coin_log_user_created', 'user_id', 'created_at'),
        Index('ix_coin_log_created', 'created_at'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'amount': self.amount,
            'source': self.source,
            'quantity': self.quantity,
            'character_id': self.character_id,
            'detail': self.detail,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<CoinLog(user_id={self.user_id}, amount={self.amount}, source='{self.source}')>"

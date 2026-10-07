"""Shop category: a named shelf of listings in the coin shop (admin-configured)."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
from src.database import Base


class ShopCategory(Base):
    """A group of shop listings, shown as one section of the shop."""
    __tablename__ = 'shop_categories'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(80), nullable=False)
    description = Column(Text)
    # Lower first. Ties fall back to the name, so a new category lands somewhere
    # predictable without the admin having to number everything.
    sort_order = Column(Integer, nullable=False, default=0)
    # Hidden from players when off, listings and all, without losing the setup.
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'sort_order': self.sort_order or 0,
            'active': bool(self.active),
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<ShopCategory(id={self.id}, name='{self.name}')>"

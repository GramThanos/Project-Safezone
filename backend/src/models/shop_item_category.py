"""Which shop categories a listing appears in - a listing may be in several."""
from sqlalchemy import Column, Integer, ForeignKey
from src.database import Base


class ShopItemCategory(Base):
    """One listing in one category."""
    __tablename__ = 'shop_item_categories'

    shop_item_id = Column(Integer, ForeignKey('shop_items.id', ondelete='CASCADE'),
                          primary_key=True)
    category_id = Column(Integer, ForeignKey('shop_categories.id', ondelete='CASCADE'),
                         primary_key=True, index=True)

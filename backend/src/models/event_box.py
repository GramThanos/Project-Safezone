"""Which boxes take part in an event, and how likely each one is."""
from sqlalchemy import Column, Integer, Float, ForeignKey, UniqueConstraint
from src.database import Base


class EventBox(Base):
    """A box eligible to be granted by an event, with its relative weight.

    Weight is relative, not a percentage: a box at 3 is three times as likely to
    be the one granted as a box at 1. A grant is a single weighted pick across an
    event's boxes.
    """
    __tablename__ = 'event_boxes'
    __table_args__ = (UniqueConstraint('event_id', 'box_id', name='uq_event_box'),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False, index=True)
    box_id = Column(Integer, ForeignKey('boxes.id', ondelete='CASCADE'), nullable=False, index=True)
    weight = Column(Float, nullable=False, default=1.0)

    def to_dict(self):
        return {'id': self.id, 'event_id': self.event_id, 'box_id': self.box_id,
                'weight': self.weight}

"""Player (game character) model with SQLAlchemy"""
from datetime import datetime
import json
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from src.database import Base


class Player(Base):
    """Player model for managing game characters"""
    __tablename__ = 'players'
    
    # Columns
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    name = Column(String(100), nullable=False, index=True)
    description = Column(Text)
    avatar = Column(String(255))
    stats = Column(Text)  # JSON stored as text
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    def __repr__(self):
        return f"<Player(id={self.id}, name='{self.name}', user_id={self.user_id})>"
    
    def get_stats(self):
        """Get stats as dictionary"""
        if self.stats:
            try:
                return json.loads(self.stats)
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}
    
    def set_stats(self, stats_dict):
        """Set stats from dictionary"""
        if stats_dict:
            self.stats = json.dumps(stats_dict)
        else:
            self.stats = '{}'
    
    def to_dict(self):
        """Convert player to dictionary"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'name': self.name,
            'description': self.description,
            'avatar': self.avatar,
            'stats': self.get_stats(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

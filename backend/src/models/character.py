"""Character (game character) model with SQLAlchemy"""
from datetime import datetime
import json
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from src.database import Base


class Character(Base):
    """Character model for managing a user's in-game characters.

    A character becomes a valid delivery target once it is linked to a real
    in-game identity (``server_id`` + ``in_game_username``) and ``verified`` via
    an approved claim request.
    """
    __tablename__ = 'characters'

    # Columns
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    name = Column(String(100), nullable=False, index=True)
    description = Column(Text)
    avatar = Column(String(255))
    stats = Column(Text)  # JSON stored as text
    # In-game identity (populated when a claim request is approved)
    server_id = Column(Integer, index=True)
    in_game_username = Column(String(32), index=True)
    verified = Column(Boolean, nullable=False, default=False)
    # `name`, `description`, `avatar` and `stats` are player-written notes, not
    # game data. Nothing syncs them from Project Zomboid, so the UI labels them
    # as notes - the verified badge vouches for the identity below, and must not
    # be read as vouching for anything the player typed.
    # `last_seen_at` is the one fact the site actually knows.
    # Last time this identity was seen on its server's online roster. Drives the
    # dormancy notice, and is worth showing on the profile regardless.
    last_seen_at = Column(DateTime, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<Character(id={self.id}, name='{self.name}', user_id={self.user_id})>"

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

    def is_deliverable(self):
        """Whether items/usables can be delivered to this character in-game."""
        return bool(self.verified and self.server_id and self.in_game_username)

    def to_dict(self):
        """Convert character to dictionary"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'name': self.name,
            'description': self.description,
            'avatar': self.avatar,
            'stats': self.get_stats(),
            'server_id': self.server_id,
            'in_game_username': self.in_game_username,
            'verified': self.verified,
            'last_seen_at': self.last_seen_at.isoformat() if self.last_seen_at else None,
            'deliverable': self.is_deliverable(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

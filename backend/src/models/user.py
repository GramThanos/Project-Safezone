"""User model with SQLAlchemy"""
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import Column, Integer, String, DateTime, Index
from src.database import Base


class User(Base):
    """User model for authentication and authorization"""
    __tablename__ = 'users'
    
    # Role constants
    ROLE_BANNED = 'banned'
    ROLE_PLAYER = 'player'
    ROLE_MODERATOR = 'moderator'
    ROLE_ADMIN = 'admin'
    
    ROLES = [ROLE_BANNED, ROLE_PLAYER, ROLE_MODERATOR, ROLE_ADMIN]
    
    # Columns
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(80), unique=True, nullable=False, index=True)
    email = Column(String(120), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default=ROLE_PLAYER, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}', role='{self.role}')>"
    
    def set_password(self, password):
        """Hash and set user password"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Check if provided password matches hash"""
        return check_password_hash(self.password_hash, password)
    
    def is_admin(self):
        """Check if user is admin"""
        return self.role == self.ROLE_ADMIN
    
    def is_moderator(self):
        """Check if user is moderator or admin"""
        return self.role in [self.ROLE_MODERATOR, self.ROLE_ADMIN]
    
    def is_banned(self):
        """Check if user is banned"""
        return self.role == self.ROLE_BANNED
    
    def to_dict(self, include_sensitive=False):
        """Convert user to dictionary"""
        data = {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'role': self.role,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
        if include_sensitive:
            data['password_hash'] = self.password_hash
        return data

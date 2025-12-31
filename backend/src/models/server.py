"""Server model for game server status with SQLAlchemy"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Index
from src.database import Base


class Server(Base):
    """Server model for tracking game servers"""
    __tablename__ = 'servers'
    
    # Columns
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    host = Column(String(255), nullable=False)
    port = Column(Integer, nullable=False)
    rcon_port = Column(Integer)
    rcon_password = Column(String(255))
    status = Column(String(50), default='offline', index=True)
    active_players = Column(Integer, default=0)
    max_players = Column(Integer, default=0)
    game_day = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    def __repr__(self):
        return f"<Server(id={self.id}, name='{self.name}', status='{self.status}')>"
    
    def to_dict(self, include_sensitive=False):
        """Convert server to dictionary"""
        data = {
            'id': self.id,
            'name': self.name,
            'host': self.host,
            'port': self.port,
            'status': self.status,
            'active_players': self.active_players,
            'max_players': self.max_players,
            'game_day': self.game_day,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
        if include_sensitive:
            data['rcon_port'] = self.rcon_port
            data['rcon_password'] = self.rcon_password
        return data

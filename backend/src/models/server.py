"""Server model for game server status with SQLAlchemy"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Index
from src.database import Base


class Server(Base):
    """Server model for tracking game servers"""
    __tablename__ = 'servers'
    
    # Columns
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), unique=True, nullable=False, index=True)
    ports = Column(JSON, nullable=False)
    rcon_port = Column(Integer)
    rcon_password = Column(String(255))
    default_state = Column(String(64), nullable=False, default='stopped') # stopped, running, sleeping
    created_at = Column(TIMESTAMP, server_default=sqlalchemy.func.now(), index=True)
    
    def __repr__(self):
        return f"<Server(id={self.id}, name='{self.name}', status='{self.status}')>"
    
    def to_dict(self, include_sensitive=False):
        """Convert server to dictionary"""
        data = {
            'id': self.id,
            'name': self.name,
            'ports': self.ports,
            'rcon_port': self.rcon_port,
            'rcon_password': self.rcon_password if include_sensitive else None,
            'default_state': self.default_state,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
        return data

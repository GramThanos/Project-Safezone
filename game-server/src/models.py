#!/usr/bin/env python3
import json
import sqlalchemy
from sqlalchemy import Column, Index, Integer, String, JSON, TIMESTAMP
import sqlalchemy.orm

class Base(sqlalchemy.orm.DeclarativeBase):
    pass

class Task(Base):
    """Task model for managing background jobs"""
    __tablename__ = 'tasks'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    status = Column(String(64), nullable=False, default='pending', index=True)
    # FIXED: Removed the double Column() wrapper
    action = Column(String(64), nullable=False, default='none') 
    data = Column(JSON, nullable=False)
    
    created_at = Column(TIMESTAMP, server_default=sqlalchemy.func.now(), index=True)
    updated_at = Column(TIMESTAMP, server_default=sqlalchemy.func.now(), onupdate=sqlalchemy.func.now())
    
    __table_args__ = (
        Index('idx_status', 'status'),
        Index('idx_created_at', 'created_at'),
    )
    
    def __repr__(self):
        return f"<Task(id={self.id}, status='{self.status}', action='{self.action}')>"
    
    def to_dict(self):
        """Convert task to dictionary with safe JSON parsing"""
        data_payload = self.data

        if isinstance(data_payload, str):
            try:
                data_payload = json.loads(data_payload)
            except (json.JSONDecodeError, TypeError):
                data_payload = {'raw_data': data_payload}
        
        return {
            'id': self.id,
            'status': self.status,
            'action': self.action,
            'data': data_payload or {},
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

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

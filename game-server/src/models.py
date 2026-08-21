#!/usr/bin/env python3
import json
import sqlalchemy
from sqlalchemy import Boolean, Column, Index, Integer, String, Text, JSON, TIMESTAMP
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
    # Public connection info shown on the site (domain or IP players connect to).
    hostname = Column(String(255))
    description = Column(Text)
    ports = Column(JSON, nullable=False)
    rcon_port = Column(Integer)
    rcon_password = Column(String(255))
    # IANA timezone (e.g. "Europe/Athens").
    timezone = Column(String(64))
    # The "primary" server is the clock the site runs on: its timezone defines
    # the daily-reward reset boundary. Exactly one server should carry this -
    # it used to be inferred from row order, which meant adding a server could
    # silently move every player's reset.
    is_primary = Column(Boolean, nullable=False, default=False)
    default_state = Column(String(64), nullable=False, default='stopped') # stopped, running, sleeping
    # Seconds a running server may sit with nobody online before it is put back
    # to sleep. 0 disables it, leaving the server up until somebody stops it.
    idle_sleep_seconds = Column(Integer, nullable=False, default=0)
    created_at = Column(TIMESTAMP, server_default=sqlalchemy.func.now(), index=True)

    def __repr__(self):
        return f"<Server(id={self.id}, name='{self.name}', status='{self.status}')>"

    def to_dict(self, include_sensitive=False):
        """Convert server to dictionary"""
        data = {
            'id': self.id,
            'name': self.name,
            'hostname': self.hostname,
            'description': self.description,
            'ports': self.ports,
            'rcon_port': self.rcon_port,
            'rcon_password': self.rcon_password if include_sensitive else None,
            'timezone': self.timezone,
            'is_primary': bool(self.is_primary),
            'default_state': self.default_state,
            'idle_sleep_seconds': self.idle_sleep_seconds or 0,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
        return data


class ServerPlayerCount(Base):
    """Time-series sample of how many players were online on a server.

    Written by each server manager's roster worker on every poll, so the site
    can chart player activity. Old rows are pruned periodically.
    """
    __tablename__ = 'server_player_counts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    server_id = Column(Integer, nullable=False, index=True)
    count = Column(Integer, nullable=False, default=0)
    created_at = Column(TIMESTAMP, server_default=sqlalchemy.func.now(), index=True)

    __table_args__ = (
        Index('idx_server_created', 'server_id', 'created_at'),
    )

    def __repr__(self):
        return f"<ServerPlayerCount(server_id={self.server_id}, count={self.count})>"

    def to_dict(self):
        return {
            'server_id': self.server_id,
            'count': self.count,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class WorkshopCollection(Base):
    """A Workshop collection this panel has installed from.

    Kept because a collection carries an *order*: the author arranged the mods,
    and for Project Zomboid that arrangement is frequently the intended load
    order. Enabling a collection's mods on a server should reproduce it rather
    than sorting by item id, which is what a set would give you.

    A table rather than a cache entry: it is small, it is written once per
    collection, and losing it to an eviction would silently downgrade "enable
    all of this, in order" back into forty manual clicks.
    """
    __tablename__ = 'workshop_collections'

    # The Workshop id, as a string - they are 64-bit and only ever compared.
    id = Column(String(32), primary_key=True)
    title = Column(String(255))
    # Ordered list of Workshop item ids. Order is the point of the record.
    items = Column(JSON, nullable=False)

    created_at = Column(TIMESTAMP, server_default=sqlalchemy.func.now())
    updated_at = Column(TIMESTAMP, server_default=sqlalchemy.func.now(),
                        onupdate=sqlalchemy.func.now())

    def __repr__(self):
        return f"<WorkshopCollection(id='{self.id}', items={len(self.items or [])})>"

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'items': list(self.items or []),
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

#!/usr/bin/env python3
import json
import random
import string
import datetime

# Custom modules
import config
import steam
import database
import models


# Logging

def _log(message):
    ts = datetime.datetime.now().isoformat()
    print(f"[{ts}][Servers] {message}")


# Servers

def get_all(limit=None, offset=0):
    """List all server with optional filtering"""
    with database.get_context_session() as session:
        query = session.query(models.Server)
        
        query = query.order_by(models.Server.name.desc())
        
        if limit:
            query = query.limit(limit).offset(offset)
        
        servers = query.all()
        return [server.to_dict() for server in servers]

def update(server_id, data=None):
    """Update server data with safe JSON parsing"""
    if not data:
        return False, "No data provided"
    
    with database.get_context_session() as session:
        server = session.query(models.Server).filter(models.Server.id == server_id).first()
        if not server:
            return False, "Server not found"
        
        if 'name' in data:
            server.name = data['name']
        if 'ports' in data:
            server.ports = data['ports']
        if 'default_state' in data:
            server.default_state = data['default_state']
                
        session.commit()
        return True, server.to_dict()

def create(data=None):
    """Create a new server"""
    if not data or 'name' not in data:
        return False
    
    with database.get_context_session() as session:
        server = models.Server(
            name=data.get('name', 'zomboid_server' + ''.join(random.choices(string.ascii_lowercase + string.digits, k=5))),
            ports=data.get('ports', [16261, 16262]),
            default_state=data.get('default_state', 'stopped')
        )
        session.add(server)
        session.commit()
        session.refresh(server)
        return server.to_dict()

def get(server_id):
    """Get specific server by ID"""
    with database.get_context_session() as session:
        server = session.query(models.Server).filter(models.Server.id == server_id).first()
        return server.to_dict() if server else None

def delete(server_id):
    """Delete a server"""
    with database.get_context_session() as session:
        server = session.query(models.Server).filter(models.Server.id == server_id).first()
        
        if not server:
            return False, "Server not found"
        
        session.delete(server)
        session.commit()
        return True, None

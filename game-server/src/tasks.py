#!/usr/bin/env python3
import json
import datetime

# Custom modules
import config
import steam
import database
import models


# Logging

def _log(message):
    ts = datetime.datetime.now().isoformat()
    print(f"[{ts}][Tasks] {message}")


# Actions

def update_server(data):
    res = steam.app_update(config.STEAM_APP_ID, beta=config.STEAM_APP_BETA, install_dir=config.STEAM_INSTALL_DIR)
    return True if res else False

def get_app_info(data):
    info = steam.app_info(config.STEAM_APP_ID)
    if not info:
        return False
    data['data'] = info
    return True

ACTIONS = {
    'update_server': update_server,
    'get_app_info': get_app_info,
}


# Tasks

def get_all(status_filter=None, limit=None, offset=0):
    """List all tasks with optional filtering using context session"""
    with database.get_context_session() as session:
        query = session.query(models.Task)
        
        if status_filter and isinstance(status_filter, str):
            query = query.filter(models.Task.status == status_filter)
        
        query = query.order_by(models.Task.created_at.desc())
        
        if limit:
            query = query.limit(limit).offset(offset)
        
        tasks = query.all()
        return [task.to_dict() for task in tasks]

def get_pending(limit=None, offset=0):
    return get_all(status_filter='pending', limit=limit, offset=offset)

def update(task_id, status, data=None):
    """Update task status and data with safe JSON parsing"""
    with database.get_context_session() as session:
        task = session.query(models.Task).filter(models.Task.id == task_id).first()
        if not task:
            return False
            
        task.status = status
        if data is not None:
            try:
                # Ensure we handle potential JSON string errors
                task.data = data if isinstance(data, dict) else json.loads(data)
            except (json.JSONDecodeError, TypeError) as e:
                _log(f"Invalid data format for task {task_id}: {e}")
                return False
                
        session.commit()
        return True

def create(data=None):
    """Create a new task"""
    with database.get_context_session() as session:
        task = models.Task(status='pending', data=(data or {}))
        session.add(task)
        session.commit()
        session.refresh(task)
        return task.id

def get(task_id):
    """Get specific task by ID"""
    with database.get_context_session() as session:
        task = session.query(models.Task).filter(models.Task.id == task_id).first()
        return task.to_dict() if task else None

def delete(task_id):
    """Delete a task (only if not processing)"""
    with database.get_context_session() as session:
        task = session.query(models.Task).filter(models.Task.id == task_id).first()
        
        if not task:
            return False, "Task not found"
        if task.status == 'processing':
            return False, "Cannot delete task that is currently processing"
        
        session.delete(task)
        session.commit()
        return True, None

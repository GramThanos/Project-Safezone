#!/usr/bin/env python3
# Task operations module

# Import necessary modules
import json
import time
import datetime

# Import custom module
import database
import task_action


def get_all(status_filter=None, limit=None, offset=0):
    """List all tasks with optional filtering"""
    session = database.get_session()
    try:
        query = session.query(database.Task)
        
        if status_filter and isinstance(status_filter, str):
            query = query.filter(database.Task.status == status_filter)
        
        query = query.order_by(database.Task.created_at.desc())
        
        if limit:
            query = query.limit(limit).offset(offset)
        
        tasks = query.all()
        database.close_session(session)
        return [task.to_dict() for task in tasks]
    except Exception as e:
        print(f"Error listing tasks: {e}")
        database.close_session(session)
        return []


def get_pending(limit=None, offset=0):
    return get_all(status_filter='pending', limit=limit, offset=offset)


def update(task_id, status, data={}):
    """Update task status and data"""
    session = database.get_session()
    try:
        task = session.query(database.Task).filter(database.Task.id == task_id).first()
        if task:
            task.status = status
            task.data = data if isinstance(data, dict) else json.loads(data)
            session.commit()
            return True
        database.close_session(session)
        return False
    except Exception as e:
        print(f"Error updating task status: {e}")
        session.rollback()
        database.close_session(session)
        return False


def create(data=None):
    """Create a new task"""
    session = database.get_session()
    try:
        # Set default data with wait message for pending tasks
        if not data:
            data = {}
        
        task = database.Task(status='pending', data=data)
        session.add(task)
        session.commit()
        session.refresh(task)
        task_id = task.id
        database.close_session(session)
        return task_id
    except Exception as e:
        print(f"Error creating task: {e}")
        session.rollback()
        database.close_session(session)
        return None


def get(task_id):
    """Get specific task by ID"""
    session = database.get_session()
    try:
        task = session.query(database.Task).filter(database.Task.id == task_id).first()
        task = task.to_dict() if task else None
        database.close_session(session)
        return task
    except Exception as e:
        print(f"Error getting task: {e}")
        database.close_session(session)
        return None


def delete(task_id):
    """Delete a task (only if not processing)"""
    session = database.get_session()
    try:
        task = session.query(database.Task).filter(database.Task.id == task_id).first()
        err = None
        res = False

        if not task:
            res = False
            err = "Task not found"
        elif task.status == 'processing':
            res = False
            err = "Cannot delete task that is currently processing"
        else:
            session.delete(task)
            session.commit()
            res = True
            err = None
        database.close_session(session)
        return res, err
    except Exception as e:
        print(f"Error deleting task: {e}")
        session.rollback()
        database.close_session(session)
        return False, str(e)


def log(message):
    """Log a message with timestamp"""
    print(f"[{datetime.datetime.now().isoformat()}] {message}")


def process(task_id):
    """Process a single task"""
    task = get(task_id)
    if not task:
        log(f"Task {task_id} not found for processing")
        return
    
    log(f"Processing task {task_id}")
    data = task['data'] if isinstance(task['data'], dict) else {}
    
    # Update status to processing
    if not update(task_id, 'processing', data):
        log(f"Failed to update task {task_id} to processing status")
        return
    
    # Process task
    try:
        task_action_func = task_action.ACTIONS.get(data.get('action'))
        if not task_action_func:
            log(f"Unknown action: {data.get('action')}")
            return False
        
        # Excecute action
        data['started_at'] = datetime.datetime.now().isoformat()
        update(task_id, 'processing', data)
        res = task_action_func(data)
        if not res:
            log(f"Action {data.get('action')} returned failure")
            data['message'] = 'Task failed'
            data['result'] = 'failure'
        else:
            log(f"Action {data.get('action')} executed successfully for task {task_id}")
            data['message'] = 'Task completed successfully'
            data['result'] = 'success'
        data['ended_at'] = datetime.datetime.now().isoformat()
        update(task_id, 'completed', data)
        return True
        
    except Exception as e:
        # Handle processing errors
        log(f"Error processing task {task_id}: {e}")
        data['message'] = 'Task failed during processing: ' + str(e)
        data['result'] = 'failure'
        update(task_id, 'completed', data)
        log(f"Task {task_id} failed")
        return False

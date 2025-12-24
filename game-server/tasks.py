"""
Task operations module
Handles all task-related database operations
"""
import json
from datetime import datetime
from database import get_db_session, close_db_session, Task


def get_pending_task():
    """Get the next pending task from the queue"""
    session = get_db_session()
    try:
        # Get oldest pending task
        task = session.query(Task).filter(
            Task.status == 'pending'
        ).order_by(Task.created_at.asc()).first()
        
        if task:
            return task.to_dict()
        return None
    except Exception as e:
        print(f"Error getting pending task: {e}")
        return None
    finally:
        close_db_session(session)


def update_task_status(task_id, status, data):
    """Update task status and data"""
    session = get_db_session()
    try:
        task = session.query(Task).filter(Task.id == task_id).first()
        if task:
            task.status = status
            task.data = data if isinstance(data, dict) else json.loads(data)
            session.commit()
            return True
        return False
    except Exception as e:
        print(f"Error updating task status: {e}")
        session.rollback()
        return False
    finally:
        close_db_session(session)


def create_task(data):
    """Create a new task"""
    session = get_db_session()
    try:
        # Set default data with wait message for pending tasks
        if not data:
            data = {}
        if 'message' not in data:
            data['message'] = 'Task is waiting to be processed'
        
        task = Task(status='pending', data=data)
        session.add(task)
        session.commit()
        session.refresh(task)
        task_id = task.id
        return task_id
    except Exception as e:
        print(f"Error creating task: {e}")
        session.rollback()
        return None
    finally:
        close_db_session(session)


def get_task_by_id(task_id):
    """Get specific task by ID"""
    session = get_db_session()
    try:
        task = session.query(Task).filter(Task.id == task_id).first()
        if task:
            return task.to_dict()
        return None
    except Exception as e:
        print(f"Error getting task: {e}")
        return None
    finally:
        close_db_session(session)


def list_tasks(status_filter=None, limit=None, offset=0):
    """List all tasks with optional filtering"""
    session = get_db_session()
    try:
        query = session.query(Task)
        
        if status_filter:
            query = query.filter(Task.status == status_filter)
        
        query = query.order_by(Task.created_at.desc())
        
        if limit:
            query = query.limit(limit).offset(offset)
        
        tasks = query.all()
        return [task.to_dict() for task in tasks]
    except Exception as e:
        print(f"Error listing tasks: {e}")
        return []
    finally:
        close_db_session(session)


def delete_task(task_id):
    """Delete a task (only if not processing)"""
    session = get_db_session()
    try:
        task = session.query(Task).filter(Task.id == task_id).first()
        
        if not task:
            return None, "Task not found"
        
        if task.status == 'processing':
            return False, "Cannot delete task that is currently processing"
        
        session.delete(task)
        session.commit()
        return True, None
    except Exception as e:
        print(f"Error deleting task: {e}")
        session.rollback()
        return False, str(e)
    finally:
        close_db_session(session)


def clear_tasks():
    """Clear all pending and completed tasks"""
    session = get_db_session()
    try:
        deleted_count = session.query(Task).filter(
            Task.status.in_(['pending', 'completed'])
        ).delete(synchronize_session=False)
        session.commit()
        return deleted_count
    except Exception as e:
        print(f"Error clearing tasks: {e}")
        session.rollback()
        return 0
    finally:
        close_db_session(session)


def process_task(task):
    """Process a single task"""
    import time
    
    task_id = task['id']
    print(f"[{datetime.now().isoformat()}] Processing task {task_id}")
    
    # Update status to processing
    processing_data = {
        'message': 'Task is being processed',
        'started_at': datetime.now().isoformat(),
        'progress': 0,
        'original_data': task['data']
    }
    
    if not update_task_status(task_id, 'processing', processing_data):
        print(f"Failed to update task {task_id} to processing status")
        return
    
    # Simulate processing work with progress updates
    try:
        # Step 1: Initialize (25% progress)
        time.sleep(1)
        processing_data['progress'] = 25
        processing_data['message'] = 'Task initialized'
        update_task_status(task_id, 'processing', processing_data)
        
        # Step 2: Processing main work (50% progress)
        time.sleep(2)
        processing_data['progress'] = 50
        processing_data['message'] = 'Processing main work'
        update_task_status(task_id, 'processing', processing_data)
        
        # Step 3: Finalizing (75% progress)
        time.sleep(1)
        processing_data['progress'] = 75
        processing_data['message'] = 'Finalizing task'
        update_task_status(task_id, 'processing', processing_data)
        
        # Step 4: Complete (100% progress)
        time.sleep(1)
        completed_data = {
            'message': 'Task completed successfully',
            'completed_at': datetime.now().isoformat(),
            'started_at': processing_data['started_at'],
            'result': 'success',
            'original_data': task['data'],
            'processed_info': {
                'steps_completed': 4,
                'total_time_seconds': 5
            }
        }
        update_task_status(task_id, 'completed', completed_data)
        
        print(f"[{datetime.now().isoformat()}] Task {task_id} completed successfully")
        
    except Exception as e:
        # Handle processing errors
        print(f"Error processing task {task_id}: {e}")
        error_data = {
            'message': 'Task failed during processing',
            'completed_at': datetime.now().isoformat(),
            'started_at': processing_data.get('started_at', datetime.now().isoformat()),
            'result': 'failed',
            'error': str(e),
            'original_data': task['data']
        }
        update_task_status(task_id, 'completed', error_data)
        print(f"[{datetime.now().isoformat()}] Task {task_id} failed")

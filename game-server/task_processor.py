"""
Task Processor Service
Processes tasks from the queue/database
Uses Redis pub/sub for real-time notifications of new tasks
"""
import os
import json
import time
from datetime import datetime
import mysql.connector
import redis

# Configuration
# IMPORTANT: Change default credentials in production!
DATABASE_HOST = os.getenv('DATABASE_HOST', 'db')
DATABASE_NAME = os.getenv('DATABASE_NAME', 'safehouse')
DATABASE_USER = os.getenv('DATABASE_USER', 'safehouse')
DATABASE_PASSWORD = os.getenv('DATABASE_PASSWORD', 'safehouse')
REDIS_HOST = os.getenv('REDIS_HOST', 'cache')
REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
PROCESS_INTERVAL = int(os.getenv('PROCESS_INTERVAL', '5'))  # seconds
REDIS_CHANNEL = 'task_notifications'


def get_db_connection():
    """Get database connection"""
    try:
        conn = mysql.connector.connect(
            host=DATABASE_HOST,
            database=DATABASE_NAME,
            user=DATABASE_USER,
            password=DATABASE_PASSWORD
        )
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        return None


def get_redis_connection():
    """Get Redis connection"""
    try:
        r = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True
        )
        return r
    except Exception as e:
        print(f"Redis connection error: {e}")
        return None


def get_pending_task():
    """Get the next pending task from the queue"""
    conn = get_db_connection()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor(dictionary=True)
        
        # Get oldest pending task
        cursor.execute("""
            SELECT id, status, data, created_at 
            FROM tasks 
            WHERE status = 'pending' 
            ORDER BY created_at ASC 
            LIMIT 1
        """)
        task = cursor.fetchone()
        cursor.close()
        
        # Parse JSON data if it's a string
        if task and isinstance(task['data'], str):
            task['data'] = json.loads(task['data'])
        
        return task
    except Exception as e:
        print(f"Error getting pending task: {e}")
        return None
    finally:
        conn.close()


def update_task_status(task_id, status, data):
    """Update task status and data"""
    conn = get_db_connection()
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE tasks SET status = %s, data = %s WHERE id = %s",
            (status, json.dumps(data), task_id)
        )
        conn.commit()
        cursor.close()
        return True
    except Exception as e:
        print(f"Error updating task status: {e}")
        return False
    finally:
        conn.close()


def process_task(task):
    """Process a single task"""
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


def run_processor():
    """Main processor loop"""
    print("Starting Task Processor Service...")
    print(f"Redis notification channel: {REDIS_CHANNEL}")
    print(f"Fallback polling interval: {PROCESS_INTERVAL} seconds")
    
    # Connect to Redis
    r = get_redis_connection()
    if not r:
        print("WARNING: Redis connection failed, falling back to polling mode")
        run_polling_mode()
        return
    
    # Create pubsub for notifications
    pubsub = r.pubsub()
    pubsub.subscribe(REDIS_CHANNEL)
    
    # Process any existing pending tasks on startup
    print("Checking for existing pending tasks on startup...")
    existing_tasks_processed = 0
    while True:
        task = get_pending_task()
        if task:
            process_task(task)
            existing_tasks_processed += 1
        else:
            break
    
    print(f"Processed {existing_tasks_processed} existing tasks on startup")
    print("Now listening for new task notifications...")
    
    # Main loop: listen for notifications
    while True:
        try:
            # Check for messages with timeout
            message = pubsub.get_message(timeout=PROCESS_INTERVAL)
            
            if message and message['type'] == 'message':
                # New task notification received
                print(f"[{datetime.now().isoformat()}] Received task notification")
                
                # Process all pending tasks (might be multiple)
                while True:
                    task = get_pending_task()
                    if task:
                        process_task(task)
                    else:
                        break
            else:
                # Timeout - check for any pending tasks (fallback)
                task = get_pending_task()
                if task:
                    print(f"[{datetime.now().isoformat()}] Found pending task via polling fallback")
                    process_task(task)
                    
        except Exception as e:
            print(f"Error in processor loop: {e}")
            time.sleep(PROCESS_INTERVAL)


def run_polling_mode():
    """Fallback polling mode when Redis is unavailable"""
    print("Running in polling mode (Redis unavailable)")
    
    while True:
        try:
            # Get next pending task
            task = get_pending_task()
            
            if task:
                process_task(task)
            else:
                # No pending tasks, wait before checking again
                time.sleep(PROCESS_INTERVAL)
                
        except Exception as e:
            print(f"Error in processor loop: {e}")
            time.sleep(PROCESS_INTERVAL)


if __name__ == '__main__':
    run_processor()

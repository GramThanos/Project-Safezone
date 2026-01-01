#!/usr/bin/env python3
import datetime
import time

# Custom modules
import config
import database
import models
import cache
import tasks


# Logging

def _log(message):
    ts = datetime.datetime.now().isoformat()
    print(f"[{ts}][Tasks Manager] {message}")


# Task Processing

def process(task_id):
    """
    Process a single task. 
    Uses a single session context for the entire lifecycle of the action.
    """
    with database.get_context_session() as session:
        task = session.query(models.Task).filter(models.Task.id == task_id).first()
        
        if not task:
            _log(f"Task {task_id} not found")
            return False

        # Initial transition to processing
        _log(f"Processing task {task_id}")
        task.status = 'processing'
        
        # Prepare data and action
        data = task.data if isinstance(task.data, dict) else {}
        action_name = data.get('action')
        task_action_func = tasks.ACTIONS.get(action_name)

        if not task_action_func:
            _log(f"Unknown action: {action_name}")
            task.status = 'completed' # or 'failed' depending on your preference
            data.update({"message": "Unknown action", "result": "failure"})
            task.data = data
            session.commit()
            return False

        # Execute the action
        data['started_at'] = datetime.datetime.now().isoformat()
        session.commit() # Checkpoint: mark as started in DB

        try:
            # We pass the data to the external action function
            success = task_action_func(data)
            
            data['result'] = 'success' if success else 'failure'
            data['message'] = 'Task completed' if success else 'Action returned False'
            _log(f"Action {action_name} result: {data['result']}")
            
        except Exception as e:
            _log(f"Execution error on task {task_id}: {e}")
            data['result'] = 'failure'
            data['message'] = f"Error: {str(e)}"

        # Finalize status and data
        data['ended_at'] = datetime.datetime.now().isoformat()
        task.status = 'completed'
        task.data = data
        session.commit()
        
        return data['result'] == 'success'

def process_pending_tasks():
    tasks_processed = 0
    try:
        pending_tasks = tasks.get_pending()
        if not pending_tasks:
            return 0

        for task in pending_tasks:
            # Added a basic safety check for task structure
            task_id = task.get('id')
            if task_id:
                res = process(task_id)
                tasks_processed += 1 if res else 0
    except Exception as e:
        _log(f"Critical error fetching/processing tasks: {e}")
    
    return tasks_processed

def manage_tasks():
    """Main manager loop with improved stability and error recovery"""
    _log("Starting Task Manager Service...")
    
    # 1. Initial backlog processing
    _log("Checking for existing pending tasks on startup...")
    initial_count = process_pending_tasks()
    _log(f"Processed {initial_count} existing tasks on startup")

    while True:
        try:
            _log(f"Subscribing to channel: {config.MANAGE_TASKS_CHANNEL}")
            pubsub = cache.subscribe_to_channel(config.MANAGE_TASKS_CHANNEL)
            
            if not pubsub:
                _log("ERROR: Failed to subscribe. Retrying in 5s...")
                time.sleep(5)
                continue

            _log("System online. Listening for new task notifications...")
            
            # Listen for messages
            for message in pubsub.listen():
                # Ignore internal Redis subscription messages
                if message['type'] != 'message':
                    continue

                # Process tasks
                count = process_pending_tasks()
                if count > 0:
                    _log(f"Processed {count} tasks in response to event")

        except Exception as e:
            _log(f"Connection lost or loop error: {e}. Reconnecting...")
            time.sleep(5)

if __name__ == '__main__':
    # Wait for DB
    _log("Checking database availability...")
    database.wait_table(models.Task, timeout=60*5)
    # Wait for Cache
    _log("Checking cache availability...")
    cache.wait()

    # Manage Tasks
    try:
        manage_tasks()
    except KeyboardInterrupt:
        _log("Service stopped")

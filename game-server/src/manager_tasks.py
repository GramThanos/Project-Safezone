"""
Task Processor Service
Processes tasks from the queue/database
Uses Redis pub/sub for real-time notifications of new tasks (event-driven)
"""
from datetime import datetime

# Import configuration and modules
from config import PROCESS_INTERVAL, REDIS_CHANNEL
from cache import get_redis_connection, subscribe_to_channel
import tasks


def run_processor():
    """Main processor loop - event-driven only"""
    print("Starting Task Processor Service...")
    print(f"Redis notification channel: {REDIS_CHANNEL}")
    print("Mode: Event-driven (Redis pub/sub only)")
    
    # Subscribe to Redis pub/sub channel
    pubsub = subscribe_to_channel()
    if not pubsub:
        print("ERROR: Cannot start processor without Redis pub/sub")
        print("Please ensure Redis is running and accessible")
        return
    
    # Process any existing pending tasks on startup
    print("Checking for existing pending tasks on startup...")
    existing_tasks_processed = 0
    while True:
        task = tasks.get_pending_task()
        if task:
            tasks.process_task(task)
            existing_tasks_processed += 1
        else:
            break
    
    print(f"Processed {existing_tasks_processed} existing tasks on startup")
    print("Now listening for new task notifications...")
    
    # Main loop: listen for notifications (event-driven)
    while True:
        try:
            # Wait for messages (blocking with timeout)
            message = pubsub.get_message(timeout=PROCESS_INTERVAL)
            
            if message and message['type'] == 'message':
                # New task notification received
                print(f"[{datetime.now().isoformat()}] Received task notification")
                
                # Process all pending tasks (might be multiple)
                while True:
                    task = tasks.get_pending_task()
                    if task:
                        tasks.process_task(task)
                    else:
                        break
                    
        except Exception as e:
            print(f"Error in processor loop: {e}")
            # Try to reconnect
            print("Attempting to reconnect to Redis...")
            pubsub = subscribe_to_channel()
            if not pubsub:
                print("ERROR: Failed to reconnect to Redis. Exiting.")
                return


if __name__ == '__main__':
    run_processor()

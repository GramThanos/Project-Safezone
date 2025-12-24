"""
Game Server Task Management API Service
RESTful API for managing tasks with authentication
"""
import os
import json
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS
import mysql.connector
import redis
from functools import wraps

app = Flask(__name__)
CORS(app)

# Configuration
# IMPORTANT: Change default credentials in production!
DATABASE_HOST = os.getenv('DATABASE_HOST', 'db')
DATABASE_NAME = os.getenv('DATABASE_NAME', 'safehouse')
DATABASE_USER = os.getenv('DATABASE_USER', 'safehouse')
DATABASE_PASSWORD = os.getenv('DATABASE_PASSWORD', 'safehouse')
REDIS_HOST = os.getenv('REDIS_HOST', 'cache')
REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
REDIS_CHANNEL = 'task_notifications'

# SECURITY WARNING: Change API_TOKEN in production!
# Set via environment variable: API_TOKEN=your-secure-token
API_TOKEN = os.getenv('API_TOKEN', 'safehouse-api-token-change-me')

# Warn if using default token
if API_TOKEN == 'safehouse-api-token-change-me':
    print("=" * 60)
    print("WARNING: Using default API token!")
    print("Change API_TOKEN environment variable in production!")
    print("=" * 60)


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


def notify_new_task():
    """Notify task processor about new task via Redis pub/sub"""
    try:
        r = get_redis_connection()
        if r:
            r.publish(REDIS_CHANNEL, 'new_task')
            return True
    except Exception as e:
        print(f"Error notifying new task: {e}")
    return False


def init_database():
    """Initialize database schema"""
    conn = get_db_connection()
    if not conn:
        print("Failed to connect to database for initialization")
        return False
    
    try:
        cursor = conn.cursor()
        
        # Create tasks table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INT AUTO_INCREMENT PRIMARY KEY,
                status VARCHAR(50) NOT NULL DEFAULT 'pending',
                data JSON NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_status (status),
                INDEX idx_created_at (created_at)
            )
        """)
        
        conn.commit()
        cursor.close()
        print("Database initialized successfully")
        return True
    except Exception as e:
        print(f"Database initialization error: {e}")
        return False
    finally:
        conn.close()


def require_auth(f):
    """Decorator to require authentication token"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.headers.get('Authorization')
        
        if not token:
            return jsonify({'error': 'No authorization token provided'}), 401
        
        # Support both "Bearer <token>" and plain token
        if token.startswith('Bearer '):
            token = token[7:]
        
        if token != API_TOKEN:
            return jsonify({'error': 'Invalid authorization token'}), 403
        
        return f(*args, **kwargs)
    return decorated_function


@app.route('/')
def index():
    """API root endpoint"""
    return jsonify({
        'name': 'Game Server Task Management API',
        'version': '1.0.0',
        'endpoints': {
            'list_tasks': 'GET /api/tasks',
            'get_task': 'GET /api/tasks/:id',
            'create_task': 'POST /api/tasks',
            'delete_task': 'DELETE /api/tasks/:id',
            'clear_tasks': 'DELETE /api/tasks'
        },
        'authentication': 'Required - Use Authorization header with Bearer token'
    })


@app.route('/api/tasks', methods=['GET'])
@require_auth
def list_tasks():
    """List all tasks with optional filtering"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 503
    
    try:
        cursor = conn.cursor(dictionary=True)
        
        # Get filter parameters
        status_filter = request.args.get('status')
        limit = request.args.get('limit', type=int)
        offset = request.args.get('offset', type=int, default=0)
        
        # Build query
        query = "SELECT id, status, data, created_at, updated_at FROM tasks"
        params = []
        
        if status_filter:
            query += " WHERE status = %s"
            params.append(status_filter)
        
        query += " ORDER BY created_at DESC"
        
        if limit:
            query += " LIMIT %s OFFSET %s"
            params.extend([limit, offset])
        
        cursor.execute(query, params)
        tasks = cursor.fetchall()
        
        # Convert datetime objects to strings and parse JSON data
        for task in tasks:
            task['created_at'] = task['created_at'].isoformat() if task['created_at'] else None
            task['updated_at'] = task['updated_at'].isoformat() if task['updated_at'] else None
            # Parse JSON data if it's a string
            if isinstance(task['data'], str):
                task['data'] = json.loads(task['data'])
        
        cursor.close()
        return jsonify({
            'tasks': tasks,
            'count': len(tasks)
        })
    except Exception as e:
        print(f"Error listing tasks: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/tasks/<int:task_id>', methods=['GET'])
@require_auth
def get_task(task_id):
    """Get specific task information"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 503
    
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, status, data, created_at, updated_at FROM tasks WHERE id = %s",
            (task_id,)
        )
        task = cursor.fetchone()
        cursor.close()
        
        if not task:
            return jsonify({'error': 'Task not found'}), 404
        
        # Convert datetime objects to strings and parse JSON data
        task['created_at'] = task['created_at'].isoformat() if task['created_at'] else None
        task['updated_at'] = task['updated_at'].isoformat() if task['updated_at'] else None
        if isinstance(task['data'], str):
            task['data'] = json.loads(task['data'])
        
        return jsonify(task)
    except Exception as e:
        print(f"Error getting task: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/tasks', methods=['POST'])
@require_auth
def create_task():
    """Create a new task"""
    if not request.is_json:
        return jsonify({'error': 'Content-Type must be application/json'}), 400
    
    data = request.get_json()
    
    if not data:
        data = {}
    
    # Set default data with wait message for pending tasks
    if 'message' not in data:
        data['message'] = 'Task is waiting to be processed'
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 503
    
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO tasks (status, data) VALUES (%s, %s)",
            ('pending', json.dumps(data))
        )
        conn.commit()
        task_id = cursor.lastrowid
        cursor.close()
        
        # Notify task processor about new task
        notify_new_task()
        
        return jsonify({
            'id': task_id,
            'status': 'pending',
            'data': data,
            'message': 'Task created successfully'
        }), 201
    except Exception as e:
        print(f"Error creating task: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
@require_auth
def delete_task(task_id):
    """Delete a pending or completed task"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 503
    
    try:
        cursor = conn.cursor(dictionary=True)
        
        # Check task status
        cursor.execute("SELECT status FROM tasks WHERE id = %s", (task_id,))
        task = cursor.fetchone()
        
        if not task:
            cursor.close()
            return jsonify({'error': 'Task not found'}), 404
        
        if task['status'] == 'processing':
            cursor.close()
            return jsonify({'error': 'Cannot delete task that is currently processing'}), 400
        
        # Delete the task
        cursor.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
        conn.commit()
        cursor.close()
        
        return jsonify({'message': f'Task {task_id} deleted successfully'})
    except Exception as e:
        print(f"Error deleting task: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/tasks', methods=['DELETE'])
@require_auth
def clear_tasks():
    """Clear all pending and completed tasks"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 503
    
    try:
        cursor = conn.cursor()
        
        # Delete all tasks except those currently processing
        cursor.execute("DELETE FROM tasks WHERE status IN ('pending', 'completed')")
        deleted_count = cursor.rowcount
        conn.commit()
        cursor.close()
        
        return jsonify({
            'message': 'Tasks cleared successfully',
            'deleted_count': deleted_count
        })
    except Exception as e:
        print(f"Error clearing tasks: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


if __name__ == '__main__':
    # Initialize database on startup
    print("Initializing database...")
    init_database()
    
    # Start Flask app
    print("Starting Task Management API Service...")
    app.run(host='0.0.0.0', port=5001, debug=False)

"""
Game Server Task Management API Service
RESTful API for managing tasks with authentication
"""
from flask import Flask, jsonify, request
from flask_cors import CORS
from functools import wraps

# Import configuration and modules
from config import API_TOKEN, warn_default_token
from database import init_database
from cache import notify_new_task
import tasks

app = Flask(__name__)
CORS(app)

# Warn if using default token
warn_default_token()


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
    try:
        # Get filter parameters
        status_filter = request.args.get('status')
        limit = request.args.get('limit', type=int)
        offset = request.args.get('offset', type=int, default=0)
        
        # Get tasks from database
        task_list = tasks.list_tasks(status_filter, limit, offset)
        
        return jsonify({
            'tasks': task_list,
            'count': len(task_list)
        })
    except Exception as e:
        print(f"Error listing tasks: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/tasks/<int:task_id>', methods=['GET'])
@require_auth
def get_task(task_id):
    """Get specific task information"""
    try:
        task = tasks.get_task_by_id(task_id)
        
        if not task:
            return jsonify({'error': 'Task not found'}), 404
        
        return jsonify(task)
    except Exception as e:
        print(f"Error getting task: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/tasks', methods=['POST'])
@require_auth
def create_task():
    """Create a new task"""
    if not request.is_json:
        return jsonify({'error': 'Content-Type must be application/json'}), 400
    
    data = request.get_json()
    
    if not data:
        data = {}
    
    try:
        task_id = tasks.create_task(data)
        
        if task_id is None:
            return jsonify({'error': 'Failed to create task'}), 500
        
        # Notify task processor about new task
        notification_sent = notify_new_task()
        if not notification_sent:
            print(f"Warning: Task {task_id} created but notification failed")
        
        return jsonify({
            'id': task_id,
            'status': 'pending',
            'data': data,
            'message': 'Task created successfully'
        }), 201
    except Exception as e:
        print(f"Error creating task: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
@require_auth
def delete_task(task_id):
    """Delete a pending or completed task"""
    try:
        success, error = tasks.delete_task(task_id)
        
        if success is None:
            return jsonify({'error': error}), 404
        
        if not success:
            return jsonify({'error': error}), 400
        
        return jsonify({'message': f'Task {task_id} deleted successfully'})
    except Exception as e:
        print(f"Error deleting task: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/tasks', methods=['DELETE'])
@require_auth
def clear_tasks():
    """Clear all pending and completed tasks"""
    try:
        deleted_count = tasks.clear_tasks()
        
        return jsonify({
            'message': 'Tasks cleared successfully',
            'deleted_count': deleted_count
        })
    except Exception as e:
        print(f"Error clearing tasks: {e}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    # Initialize database on startup
    print("Initializing database...")
    init_database()
    
    # Start Flask app
    print("Starting Task Management API Service...")
    app.run(host='0.0.0.0', port=5001, debug=False)

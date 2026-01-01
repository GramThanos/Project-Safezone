#!/usr/bin/env python3
# Manager with a RESTful API

from flask import Flask, jsonify, request
from functools import wraps
import random
import string
import datetime

# Import configuration and modules
import config
import database
import cache
import tasks
import servers


app = Flask(__name__)

# Logging
def _log(message):
    ts = datetime.datetime.now().isoformat()
    print(f"[{ts}][API Manager] {message}")

# Protect endpoints with token authentication
def require_auth(f):
    """Decorator to require authentication token"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # If no API_TOKEN is set, skip authentication
        if not config.MANAGER_API_TOKEN:
            return f(*args, **kwargs)
        
        # Get token from Authorization header
        token = request.headers.get('Authorization')
        token = token[7:] if token and token.startswith('Bearer ') else token
        
        # Validate token
        if not token or token != config.MANAGER_API_TOKEN:
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



# Task Endpoints

@app.route('/api/tasks', methods=['GET'])
@require_auth
def list_tasks():
    """List all tasks with optional filtering"""
    try:
        # Get filter parameters
        status_filter = request.args.get('status', type=str, default=None)
        limit = request.args.get('limit', type=int, default=None)
        offset = request.args.get('offset', type=int, default=0)
        
        # Get tasks from database
        task_list = tasks.get_all(status_filter, limit, offset)
        
        return jsonify({
            'data': task_list,
            'count': len(task_list),
            'message': 'Tasks retrieved successfully'
        })
    except Exception as e:
        _log(f"Error listing tasks: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/tasks/<int:task_id>', methods=['GET'])
@require_auth
def get_task(task_id):
    """Get specific task information"""
    try:
        task = tasks.get(task_id)
        
        if not task:
            return jsonify({'error': 'Task not found'}), 404
        
        return jsonify({
            'data': task,
            'message': 'Task retrieved successfully'
        })
    except Exception as e:
        _log(f"Error getting task: {e}")
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
        task = tasks.create(data)
        if not task:
            return jsonify({'error': 'Failed to create task'}), 500
        
        # Notify task processor about new task
        notification_sent = cache.broadcast_to_channel(config.MANAGE_TASKS_CHANNEL, {'action': 'new_task', 'task_id': task['id']})
        if not notification_sent:
            _log(f"Warning: Task {task['id']} created but notification failed")
        
        return jsonify({
            'data': task,
            'message': 'Task created successfully'
        }), 201
    except Exception as e:
        _log(f"Error creating task: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
@require_auth
def delete_task(task_id):
    """Delete a pending or completed task"""
    try:
        success, error = tasks.delete(task_id)
        
        if success is None:
            return jsonify({'error': error}), 404
        
        if not success:
            return jsonify({'error': error}), 400
        
        return jsonify({
            'data': {'id': task_id},
            'message': f'Task deleted successfully'
        })
    except Exception as e:
        _log(f"Error deleting task: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/tasks', methods=['DELETE'])
@require_auth
def clear_tasks():
    """Clear all pending and completed tasks"""
    try:
        deleted_count = tasks.clear()
        
        return jsonify({
            'data': {},
            'message': 'Tasks cleared successfully',
            'count': deleted_count
        })
    except Exception as e:
        _log(f"Error clearing tasks: {e}")
        return jsonify({'error': str(e)}), 500


# Server Endpoints

@app.route('/api/servers', methods=['GET'])
@require_auth
def list_servers():
    """List all servers with optional filtering"""
    try:
        # Get filter parameters
        limit = request.args.get('limit', type=int, default=None)
        offset = request.args.get('offset', type=int, default=0)
        
        # Get servers from database
        servers_list = servers.get_all(limit, offset)
        
        return jsonify({
            'data': servers_list,
            'count': len(servers_list),
            'message': 'Servers retrieved successfully'
        })
    except Exception as e:
        _log(f"Error listing servers: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<int:server_id>', methods=['GET'])
@require_auth
def get_server(server_id):
    """Get specific server information"""
    try:
        server = servers.get(server_id)
        
        if not server:
            return jsonify({'error': 'Server not found'}), 404
        
        return jsonify({
            'data': server,
            'message': 'Server retrieved successfully'
        })
    except Exception as e:
        _log(f"Error getting server: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers', methods=['POST'])
@require_auth
def create_server():
    """Create a new server"""
    if not request.is_json:
        return jsonify({'error': 'Content-Type must be application/json'}), 400
    
    data = request.get_json()
    
    # Validation
    if 'name' not in data:
        return jsonify({'error': 'Missing name'}), 400
    if 'ports' in data and not isinstance(data['ports'], list):
        return jsonify({'error': 'Ports must be a list'}), 400
    for port in data.get('ports', []):
        if not isinstance(port, int) or port <= 0 or port > 65535:
            return jsonify({'error': f'Invalid port number: {port}'}), 400
    if 'default_state' in data and data['default_state'] not in ['stopped', 'running', 'sleeping']:
        return jsonify({'error': 'Invalid default_state'}), 400
    
    data = {
        'name': data.get('name', 'zomboid_server' + ''.join(random.choices(string.ascii_lowercase + string.digits, k=5))),
        'ports': data.get('ports', [16261, 16262]),
        'default_state': data.get('default_state', 'stopped')
    }
    
    try:
        server = servers.create(data)
        if not server:
            return jsonify({'error': 'Failed to create server'}), 500
        
        # Notify task processor about new task
        notification_sent = cache.broadcast_to_channel(config.MANAGE_GAME_SERVERS_CHANNEL, {'command': 'update-managers'})
        if not notification_sent:
            _log(f"Warning: Server {server['id']} created but notification failed")
        
        return jsonify({
            'data': server,
            'message': 'Server created successfully'
        }), 201
    except Exception as e:
        _log(f"Error creating server: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<int:server_id>', methods=['PUT'])
@require_auth
def update_server(server_id):
    """Update server configuration (ports, state, name)"""
    if not request.is_json:
        return jsonify({'error': 'Content-Type must be application/json'}), 400
    
    data = request.get_json()
    to_update = {}
    
    # Validation
    if 'name' in data:
        return jsonify({'error': 'Server name can not be changed'}), 400
    if 'ports' in data:
        if not isinstance(data['ports'], list):
            return jsonify({'error': 'Ports must be a list'}), 400
        for port in data['ports']:
            if not isinstance(port, int) or port <= 0 or port > 65535:
                return jsonify({'error': f'Invalid port number: {port}'}), 400
        to_update['ports'] = data['ports']
    if 'default_state' in data:
        if data['default_state'] not in ['stopped', 'running', 'sleeping']:
            return jsonify({'error': 'Invalid default_state'}), 400
        to_update['default_state'] = data['default_state']
    
    data = to_update
    
    try:
        error, info = servers.update(server_id, data)
        if error:
            return jsonify({'error': f"Failed to update server: {error}"}), 500
        
        return jsonify({
            'data': info,
            'message': 'Server updated successfully'
        }), 200
    except Exception as e:
        _log(f"Error updating server: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<int:server_id>', methods=['DELETE'])
@require_auth
def delete_server(server_id):
    """Remove a server from the database"""
    try:
        success, error = servers.delete(server_id)
        
        if not success:
            return jsonify({'error': error}), 500
        
        # Notify task processor about new task
        notification_sent = cache.broadcast_to_channel(config.MANAGE_GAME_SERVERS_CHANNEL, {'command': 'update-managers'})
        if not notification_sent:
            _log(f"Warning: Server {server_id} deleted but notification failed")
        
        return jsonify({
            'data': {'id': server_id},
            'message': f'Server deleted successfully'
        })
    except Exception as e:
        _log(f"Error deleting server: {e}")
        return jsonify({'error': str(e)}), 500



if __name__ == '__main__':
    # Initialize database on startup
    _log("Initializing database...")
    database.init()
    _log("Checking cache availability...")
    cache.wait()
    
    # Start Flask app
    _log("Starting Task Management API Service...")
    app.run(host=config.MANAGER_API_HOST, port=config.MANAGER_API_PORT, debug=False)

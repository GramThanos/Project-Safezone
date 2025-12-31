"""Admin panel routes"""
from flask import Blueprint, request, jsonify
from src.database import db
from src.models.user import User
from src.models.server import Server
from src.middleware.auth import moderator_required, admin_required
import requests
import os

admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')


@admin_bp.route('/users', methods=['GET'])
@moderator_required
def get_users(current_user):
    """Get all users (moderator/admin only)"""
    try:
        role = request.args.get('role')
        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))
        
        with db.get_db() as conn:
            users = User.get_all(conn, role=role, limit=limit, offset=offset)
            return jsonify({
                'users': [u.to_dict() for u in users]
            }), 200
    except Exception as e:
        print(f"Get users error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/users/<int:user_id>', methods=['PUT'])
@admin_required
def update_user_role(current_user, user_id):
    """Update user role (admin only)"""
    data = request.get_json()
    
    if not data or 'role' not in data:
        return jsonify({'error': 'Role is required'}), 400
    
    if data['role'] not in User.ROLES:
        return jsonify({'error': 'Invalid role'}), 400
    
    try:
        with db.get_db() as conn:
            user = User.find_by_id(conn, user_id)
            
            if not user:
                return jsonify({'error': 'User not found'}), 404
            
            user.role = data['role']
            user.save(conn)
            
            return jsonify({
                'message': 'User role updated successfully',
                'user': user.to_dict()
            }), 200
    except Exception as e:
        print(f"Update user role error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/servers', methods=['GET'])
@moderator_required
def get_servers(current_user):
    """Get all servers (moderator/admin only)"""
    try:
        status = request.args.get('status')
        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))
        
        with db.get_db() as conn:
            servers = Server.get_all(conn, status=status, limit=limit, offset=offset)
            return jsonify({
                'servers': [s.to_dict() for s in servers]
            }), 200
    except Exception as e:
        print(f"Get servers error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/servers', methods=['POST'])
@admin_required
def create_server(current_user):
    """Create new server (admin only)"""
    data = request.get_json()
    
    if not data or not data.get('name') or not data.get('host') or not data.get('port'):
        return jsonify({'error': 'Name, host, and port are required'}), 400
    
    try:
        with db.get_db() as conn:
            server = Server(
                name=data['name'],
                host=data['host'],
                port=data['port'],
                rcon_port=data.get('rcon_port'),
                rcon_password=data.get('rcon_password'),
                max_players=data.get('max_players', 0)
            )
            server.save(conn)
            
            return jsonify({
                'message': 'Server created successfully',
                'server': server.to_dict()
            }), 201
    except Exception as e:
        print(f"Create server error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/servers/<int:server_id>', methods=['PUT'])
@admin_required
def update_server(current_user, server_id):
    """Update server (admin only)"""
    data = request.get_json()
    
    try:
        with db.get_db() as conn:
            server = Server.find_by_id(conn, server_id)
            
            if not server:
                return jsonify({'error': 'Server not found'}), 404
            
            # Update server fields
            if 'name' in data:
                server.name = data['name']
            if 'host' in data:
                server.host = data['host']
            if 'port' in data:
                server.port = data['port']
            if 'rcon_port' in data:
                server.rcon_port = data['rcon_port']
            if 'rcon_password' in data:
                server.rcon_password = data['rcon_password']
            if 'max_players' in data:
                server.max_players = data['max_players']
            
            server.save(conn)
            
            return jsonify({
                'message': 'Server updated successfully',
                'server': server.to_dict(include_sensitive=True)
            }), 200
    except Exception as e:
        print(f"Update server error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/servers/<int:server_id>', methods=['DELETE'])
@admin_required
def delete_server(current_user, server_id):
    """Delete server (admin only)"""
    try:
        with db.get_db() as conn:
            server = Server.find_by_id(conn, server_id)
            
            if not server:
                return jsonify({'error': 'Server not found'}), 404
            
            server.delete(conn)
            
            return jsonify({'message': 'Server deleted successfully'}), 200
    except Exception as e:
        print(f"Delete server error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/tasks', methods=['GET'])
@moderator_required
def get_tasks(current_user):
    """Get tasks from game server API (moderator/admin only)"""
    try:
        api_url = os.getenv('GAME_SERVER_API_URL', 'http://game-server:5001')
        api_token = os.getenv('API_TOKEN', 'safezone-api-token-change-me')
        
        response = requests.get(
            f'{api_url}/api/tasks',
            headers={'Authorization': f'Bearer {api_token}'}
        )
        
        if response.status_code == 200:
            return jsonify(response.json()), 200
        else:
            return jsonify({'error': 'Failed to fetch tasks'}), response.status_code
    except Exception as e:
        print(f"Get tasks error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/tasks', methods=['POST'])
@moderator_required
def create_task(current_user):
    """Create task in game server API (moderator/admin only)"""
    try:
        data = request.get_json()
        api_url = os.getenv('GAME_SERVER_API_URL', 'http://game-server:5001')
        api_token = os.getenv('API_TOKEN', 'safezone-api-token-change-me')
        
        response = requests.post(
            f'{api_url}/api/tasks',
            json=data,
            headers={'Authorization': f'Bearer {api_token}'}
        )
        
        if response.status_code in [200, 201]:
            return jsonify(response.json()), response.status_code
        else:
            return jsonify({'error': 'Failed to create task'}), response.status_code
    except Exception as e:
        print(f"Create task error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

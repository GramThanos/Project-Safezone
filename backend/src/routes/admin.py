"""Admin panel routes with SQLAlchemy"""
import logging
from flask import Blueprint, request, jsonify, current_app
from src.database import db
from src.models.user import User
from src.models.server import Server
from src.middleware.auth import moderator_required, admin_required
import requests

logger = logging.getLogger(__name__)
admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')


@admin_bp.route('/users', methods=['GET'])
@moderator_required
def get_users(current_user):
    """Get all users (moderator/admin only)"""
    try:
        role = request.args.get('role')
        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))
        
        with db.get_db() as session:
            query = session.query(User)
            if role:
                query = query.filter_by(role=role)
            users = query.limit(limit).offset(offset).all()
            
            return jsonify({
                'users': [u.to_dict() for u in users]
            }), 200
    except Exception as e:
        logger.error(f"Get users error: {e}")
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
        with db.get_db() as session:
            user = session.query(User).filter_by(id=user_id).first()
            
            if not user:
                return jsonify({'error': 'User not found'}), 404
            
            user.role = data['role']
            
            return jsonify({
                'message': 'User role updated successfully',
                'user': user.to_dict()
            }), 200
    except Exception as e:
        logger.error(f"Update user role error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/servers', methods=['GET'])
@moderator_required
def get_servers(current_user):
    """Get all servers (moderator/admin only)"""
    try:
        status = request.args.get('status')
        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))
        
        with db.get_db() as session:
            query = session.query(Server)
            if status:
                query = query.filter_by(status=status)
            servers = query.limit(limit).offset(offset).all()
            
            return jsonify({
                'servers': [s.to_dict() for s in servers]
            }), 200
    except Exception as e:
        logger.error(f"Get servers error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/servers', methods=['POST'])
@admin_required
def create_server(current_user):
    """Create new server (admin only)"""
    data = request.get_json()
    
    if not data or not data.get('name') or not data.get('host') or not data.get('port'):
        return jsonify({'error': 'Name, host, and port are required'}), 400
    
    try:
        with db.get_db() as session:
            server = Server(
                name=data['name'],
                host=data['host'],
                port=data['port'],
                rcon_port=data.get('rcon_port'),
                rcon_password=data.get('rcon_password'),
                max_players=data.get('max_players', 0)
            )
            session.add(server)
            session.flush()  # Flush to get server ID
            
            return jsonify({
                'message': 'Server created successfully',
                'server': server.to_dict(include_sensitive=True)
            }), 201
    except Exception as e:
        logger.error(f"Create server error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/servers/<int:server_id>', methods=['PUT'])
@admin_required
def update_server(current_user, server_id):
    """Update server (admin only)"""
    data = request.get_json()
    
    try:
        with db.get_db() as session:
            server = session.query(Server).filter_by(id=server_id).first()
            
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
            if 'status' in data:
                server.status = data['status']
            
            return jsonify({
                'message': 'Server updated successfully',
                'server': server.to_dict(include_sensitive=True)
            }), 200
    except Exception as e:
        logger.error(f"Update server error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/servers/<int:server_id>', methods=['DELETE'])
@admin_required
def delete_server(current_user, server_id):
    """Delete server (admin only)"""
    try:
        with db.get_db() as session:
            server = session.query(Server).filter_by(id=server_id).first()
            
            if not server:
                return jsonify({'error': 'Server not found'}), 404
            
            session.delete(server)
            
            return jsonify({'message': 'Server deleted successfully'}), 200
    except Exception as e:
        logger.error(f"Delete server error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/tasks', methods=['GET'])
@moderator_required
def get_tasks(current_user):
    """Get all tasks from game server (moderator/admin only)"""
    try:
        api_url = current_app.config['GAME_SERVER_API_URL']
        api_token = current_app.config['API_TOKEN']
        
        response = requests.get(
            f'{api_url}/api/tasks',
            headers={'Authorization': f'Bearer {api_token}'},
            timeout=10
        )
        
        if response.status_code == 200:
            return jsonify(response.json()), 200
        else:
            logger.error(f"Game server API error: {response.status_code}")
            return jsonify({'error': 'Failed to fetch tasks from game server'}), 500
    
    except requests.RequestException as e:
        logger.error(f"Request to game server failed: {e}")
        return jsonify({'error': 'Game server unavailable'}), 503
    except Exception as e:
        logger.error(f"Get tasks error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/tasks', methods=['POST'])
@moderator_required
def create_task(current_user):
    """Create new task on game server (moderator/admin only)"""
    data = request.get_json()
    
    if not data or not data.get('action'):
        return jsonify({'error': 'Task action is required'}), 400
    
    try:
        api_url = current_app.config['GAME_SERVER_API_URL']
        api_token = current_app.config['API_TOKEN']
        
        response = requests.post(
            f'{api_url}/api/tasks',
            headers={
                'Authorization': f'Bearer {api_token}',
                'Content-Type': 'application/json'
            },
            json=data,
            timeout=10
        )
        
        if response.status_code in [200, 201]:
            return jsonify(response.json()), response.status_code
        else:
            logger.error(f"Game server API error: {response.status_code}")
            return jsonify({'error': 'Failed to create task on game server'}), 500
    
    except requests.RequestException as e:
        logger.error(f"Request to game server failed: {e}")
        return jsonify({'error': 'Game server unavailable'}), 503
    except Exception as e:
        logger.error(f"Create task error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

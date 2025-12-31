"""Player management routes"""
from flask import Blueprint, request, jsonify
from src.database import db
from src.models.player import Player
from src.middleware.auth import token_required

players_bp = Blueprint('players', __name__, url_prefix='/api/players')


@players_bp.route('', methods=['GET'])
@token_required
def get_players(current_user):
    """Get all players for current user"""
    try:
        with db.get_db() as conn:
            players = Player.find_by_user(conn, current_user['user_id'])
            return jsonify({
                'players': [p.to_dict() for p in players]
            }), 200
    except Exception as e:
        print(f"Get players error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@players_bp.route('/<int:player_id>', methods=['GET'])
@token_required
def get_player(current_user, player_id):
    """Get specific player"""
    try:
        with db.get_db() as conn:
            player = Player.find_by_id(conn, player_id)
            
            if not player:
                return jsonify({'error': 'Player not found'}), 404
            
            # Check if player belongs to current user
            if player.user_id != current_user['user_id']:
                return jsonify({'error': 'Access denied'}), 403
            
            return jsonify({'player': player.to_dict()}), 200
    except Exception as e:
        print(f"Get player error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@players_bp.route('', methods=['POST'])
@token_required
def create_player(current_user):
    """Create new player"""
    data = request.get_json()
    
    if not data or not data.get('name'):
        return jsonify({'error': 'Player name is required'}), 400
    
    try:
        with db.get_db() as conn:
            player = Player(
                user_id=current_user['user_id'],
                name=data['name'],
                description=data.get('description', ''),
                avatar=data.get('avatar', ''),
                stats=data.get('stats', {})
            )
            player.save(conn)
            
            return jsonify({
                'message': 'Player created successfully',
                'player': player.to_dict()
            }), 201
    except Exception as e:
        print(f"Create player error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@players_bp.route('/<int:player_id>', methods=['PUT'])
@token_required
def update_player(current_user, player_id):
    """Update player"""
    data = request.get_json()
    
    try:
        with db.get_db() as conn:
            player = Player.find_by_id(conn, player_id)
            
            if not player:
                return jsonify({'error': 'Player not found'}), 404
            
            # Check if player belongs to current user
            if player.user_id != current_user['user_id']:
                return jsonify({'error': 'Access denied'}), 403
            
            # Update player fields
            if 'name' in data:
                player.name = data['name']
            if 'description' in data:
                player.description = data['description']
            if 'avatar' in data:
                player.avatar = data['avatar']
            if 'stats' in data:
                player.stats = data['stats']
            
            player.save(conn)
            
            return jsonify({
                'message': 'Player updated successfully',
                'player': player.to_dict()
            }), 200
    except Exception as e:
        print(f"Update player error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@players_bp.route('/<int:player_id>', methods=['DELETE'])
@token_required
def delete_player(current_user, player_id):
    """Delete player"""
    try:
        with db.get_db() as conn:
            player = Player.find_by_id(conn, player_id)
            
            if not player:
                return jsonify({'error': 'Player not found'}), 404
            
            # Check if player belongs to current user
            if player.user_id != current_user['user_id']:
                return jsonify({'error': 'Access denied'}), 403
            
            player.delete(conn)
            
            return jsonify({'message': 'Player deleted successfully'}), 200
    except Exception as e:
        print(f"Delete player error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

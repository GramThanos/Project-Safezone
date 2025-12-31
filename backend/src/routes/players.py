"""Player management routes"""
import logging
from flask import Blueprint, request, jsonify
from src.database import db
from src.models.player import Player
from src.middleware.auth import token_required

logger = logging.getLogger(__name__)
players_bp = Blueprint('players', __name__, url_prefix='/api/players')


@players_bp.route('', methods=['GET'])
@token_required
def get_players(current_user):
    """Get all players for current user"""
    try:
        with db.get_db() as session:
            players = session.query(Player).filter_by(user_id=current_user['user_id']).all()
            return jsonify({
                'players': [p.to_dict() for p in players]
            }), 200
    except Exception as e:
        logger.error(f"Get players error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@players_bp.route('/<int:player_id>', methods=['GET'])
@token_required
def get_player(current_user, player_id):
    """Get specific player"""
    try:
        with db.get_db() as session:
            player = session.query(Player).filter_by(id=player_id).first()
            
            if not player:
                return jsonify({'error': 'Player not found'}), 404
            
            # Check if player belongs to current user
            if player.user_id != current_user['user_id']:
                return jsonify({'error': 'Access denied'}), 403
            
            return jsonify({'player': player.to_dict()}), 200
    except Exception as e:
        logger.error(f"Get player error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@players_bp.route('', methods=['POST'])
@token_required
def create_player(current_user):
    """Create new player"""
    data = request.get_json()
    
    if not data or not data.get('name'):
        return jsonify({'error': 'Player name is required'}), 400
    
    try:
        with db.get_db() as session:
            player = Player(
                user_id=current_user['user_id'],
                name=data['name'],
                description=data.get('description', ''),
                avatar=data.get('avatar', '')
            )
            if 'stats' in data:
                player.set_stats(data['stats'])
            
            session.add(player)
            session.flush()  # Flush to get player ID
            
            return jsonify({
                'message': 'Player created successfully',
                'player': player.to_dict()
            }), 201
    except Exception as e:
        logger.error(f"Create player error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@players_bp.route('/<int:player_id>', methods=['PUT'])
@token_required
def update_player(current_user, player_id):
    """Update player"""
    data = request.get_json()
    
    try:
        with db.get_db() as session:
            player = session.query(Player).filter_by(id=player_id).first()
            
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
                player.set_stats(data['stats'])
            
            return jsonify({
                'message': 'Player updated successfully',
                'player': player.to_dict()
            }), 200
    except Exception as e:
        logger.error(f"Update player error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@players_bp.route('/<int:player_id>', methods=['DELETE'])
@token_required
def delete_player(current_user, player_id):
    """Delete player"""
    try:
        with db.get_db() as session:
            player = session.query(Player).filter_by(id=player_id).first()
            
            if not player:
                return jsonify({'error': 'Player not found'}), 404
            
            # Check if player belongs to current user
            if player.user_id != current_user['user_id']:
                return jsonify({'error': 'Access denied'}), 403
            
            session.delete(player)
            
            return jsonify({'message': 'Player deleted successfully'}), 200
    except Exception as e:
        logger.error(f"Delete player error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

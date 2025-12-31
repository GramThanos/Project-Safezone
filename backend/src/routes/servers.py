"""Server status routes"""
import logging
from flask import Blueprint, jsonify
from src.database import db
from src.models.server import Server
import redis
import os

logger = logging.getLogger(__name__)
servers_bp = Blueprint('servers', __name__, url_prefix='/api/servers')


def get_redis_connection():
    """Get Redis connection"""
    try:
        r = redis.Redis(
            host=os.getenv('REDIS_HOST', 'cache'),
            port=int(os.getenv('REDIS_PORT', '6379')),
            decode_responses=True
        )
        return r
    except Exception as e:
        logger.error(f"Redis connection error: {e}")
        return None


@servers_bp.route('', methods=['GET'])
def get_all_servers():
    """Get all servers with status (public endpoint)"""
    try:
        with db.get_db() as conn:
            servers = Server.get_all(conn)
            return jsonify({
                'servers': [s.to_dict() for s in servers]
            }), 200
    except Exception as e:
        logger.error(f"Get servers error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@servers_bp.route('/<int:server_id>', methods=['GET'])
def get_server(server_id):
    """Get specific server (public endpoint)"""
    try:
        with db.get_db() as conn:
            server = Server.find_by_id(conn, server_id)
            
            if not server:
                return jsonify({'error': 'Server not found'}), 404
            
            return jsonify({'server': server.to_dict()}), 200
    except Exception as e:
        logger.error(f"Get server error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@servers_bp.route('/status', methods=['GET'])
def get_servers_status():
    """Get all servers status from cache and database"""
    try:
        r = get_redis_connection()
        with db.get_db() as conn:
            servers = Server.get_all(conn)
            
            servers_data = []
            for server in servers:
                server_dict = server.to_dict()
                
                # Try to get updated status from Redis cache
                if r:
                    try:
                        cache_key = f'server:{server.id}:status'
                        cached_status = r.get(cache_key)
                        if cached_status:
                            server_dict['status'] = cached_status
                        
                        cache_key = f'server:{server.id}:active_players'
                        cached_players = r.get(cache_key)
                        if cached_players:
                            server_dict['active_players'] = int(cached_players)
                        
                        cache_key = f'server:{server.id}:game_day'
                        cached_day = r.get(cache_key)
                        if cached_day:
                            server_dict['game_day'] = int(cached_day)
                    except Exception as e:
                        logger.error(f"Redis cache read error: {e}")
                
                servers_data.append(server_dict)
            
            return jsonify({
                'servers': servers_data
            }), 200
    except Exception as e:
        logger.error(f"Get servers status error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

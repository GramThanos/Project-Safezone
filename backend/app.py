"""
Flask API backend for Project Safezone - Project Zomboid Server Manager
"""
import os
import logging
import redis
from flask import Flask, jsonify
from flask_cors import CORS

# Import routes
from src.routes.auth import auth_bp
from src.routes.players import players_bp
from src.routes.servers import servers_bp
from src.routes.admin import admin_bp
from src.database import db
from src.utils.redis_utils import get_redis_connection

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend requests

# Register blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(players_bp)
app.register_blueprint(servers_bp)
app.register_blueprint(admin_bp)


@app.route('/')
def index():
    """API root endpoint"""
    return jsonify({
        'name': 'Project Safezone API',
        'version': '2.0.0',
        'endpoints': {
            'health': '/health',
            'auth': {
                'signin': '/api/auth/signin',
                'signup': '/api/auth/signup',
                'me': '/api/auth/me'
            },
            'players': '/api/players',
            'servers': '/api/servers',
            'admin': {
                'users': '/api/admin/users',
                'servers': '/api/admin/servers',
                'tasks': '/api/admin/tasks'
            }
        }
    })


@app.route('/health')
def health():
    """Health check endpoint"""
    status = {
        'status': 'healthy',
        'database': 'disconnected',
        'cache': 'disconnected',
        'game_server': 'unknown'
    }
    
    # Check database
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('SELECT 1')
                cursor.fetchone()
                status['database'] = 'connected'
            finally:
                cursor.close()
    except Exception as e:
        logger.error(f"Database health check error: {e}")
        status['database'] = 'disconnected'
    
    # Check Redis
    r = get_redis_connection()
    if r:
        try:
            r.ping()
            status['cache'] = 'connected'
            # Get game server status from cache
            game_status = r.get('game_server_status')
            if game_status:
                status['game_server'] = game_status
        except redis.RedisError as e:
            logger.error(f"Redis error in health check: {e}")
            pass
    
    return jsonify(status)


if __name__ == '__main__':
    # Initialize database
    try:
        db.init_db()
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
    
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(host='0.0.0.0', port=5000, debug=debug_mode)

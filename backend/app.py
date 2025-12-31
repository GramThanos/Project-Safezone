"""
Flask API backend for Project Safezone - Project Zomboid Server Manager
"""
import os
from flask import Flask, jsonify
from flask_cors import CORS
import redis

# Import routes
from src.routes.auth import auth_bp
from src.routes.players import players_bp
from src.routes.servers import servers_bp
from src.routes.admin import admin_bp
from src.database import db

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend requests

# Configuration from environment variables
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['DATABASE_HOST'] = os.getenv('DATABASE_HOST', 'db')
app.config['DATABASE_NAME'] = os.getenv('DATABASE_NAME', 'safezone')
app.config['DATABASE_USER'] = os.getenv('DATABASE_USER', 'safezone')
app.config['DATABASE_PASSWORD'] = os.getenv('DATABASE_PASSWORD', 'safezone')
app.config['REDIS_HOST'] = os.getenv('REDIS_HOST', 'cache')
app.config['REDIS_PORT'] = int(os.getenv('REDIS_PORT', '6379'))

# Register blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(players_bp)
app.register_blueprint(servers_bp)
app.register_blueprint(admin_bp)


def get_redis_connection():
    """Get Redis connection"""
    try:
        r = redis.Redis(
            host=app.config['REDIS_HOST'],
            port=app.config['REDIS_PORT'],
            decode_responses=True
        )
        return r
    except Exception as e:
        print(f"Redis connection error: {e}")
        return None


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
            cursor.execute('SELECT 1')
            cursor.fetchone()
            status['database'] = 'connected'
    except Exception as e:
        print(f"Database health check error: {e}")
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
            print(f"Redis error in health check: {e}")
            pass
    
    return jsonify(status)


if __name__ == '__main__':
    # Initialize database
    try:
        db.init_db()
    except Exception as e:
        print(f"Database initialization error: {e}")
    
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(host='0.0.0.0', port=5000, debug=debug_mode)

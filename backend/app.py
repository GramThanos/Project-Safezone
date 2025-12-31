"""
Flask API backend for Project Safezone - Project Zomboid Server Manager
"""
import logging
import redis
from flask import Flask, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Import configuration
from src.config import configure_app

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

# Apply centralized configuration
configure_app(app)

# Initialize database with app configuration
db.init_app(app)

# CORS Configuration - restrict to specific origins
CORS(app, 
     origins=app.config['ALLOWED_ORIGINS'],
     supports_credentials=True,
     methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
     allow_headers=['Content-Type', 'Authorization'])

# Rate Limiting - using Redis as storage
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri=app.config['RATELIMIT_STORAGE_URI'],
    default_limits=app.config['RATELIMIT_DEFAULT_LIMITS'],
    storage_options={"socket_connect_timeout": 30},
    strategy="fixed-window"
)

# Security Headers Middleware
@app.after_request
def add_security_headers(response):
    """Add security headers to all responses"""
    # Prevent clickjacking
    response.headers['X-Frame-Options'] = 'DENY'
    # Prevent MIME sniffing
    response.headers['X-Content-Type-Options'] = 'nosniff'
    # Enable XSS protection
    response.headers['X-XSS-Protection'] = '1; mode=block'
    # Content Security Policy
    response.headers['Content-Security-Policy'] = "default-src 'self'"
    # Strict Transport Security (HTTPS only)
    if app.config['HTTPS_ENABLED']:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    # Referrer Policy
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    # Permissions Policy
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
    return response

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
    
    app.run(host='0.0.0.0', port=5000, debug=app.config['FLASK_DEBUG'])

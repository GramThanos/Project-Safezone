"""
Flask API backend for Project Safezone - Project Zomboid Server Manager
"""
import logging
import redis
from flask import Flask, jsonify, request
from sqlalchemy import text
from flask_cors import CORS

# Import configuration
from src.config import Config, configure_app
from src.extensions import limiter

# Import routes
from src.routes.auth import auth_bp
from src.routes.characters import characters_bp
from src.routes.servers import servers_bp
from src.routes.site import site_bp
from src.routes.admin import admin_bp
from src.routes.claims import claims_bp
from src.routes.rewards import rewards_bp
from src.routes.boxes import boxes_bp
from src.routes.inventory import inventory_bp
from src.routes.invitations import invitations_bp
from src.routes.notifications import notifications_bp
from src.routes.reports import reports_bp
from src.database import db
from src.utils.redis_utils import get_redis_connection
from src.utils.game_server import gs_request
from src.utils.logging_setup import configure as configure_logging

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

# Initialize Redis connection pool
from src.utils.redis_utils import init_redis_pool
init_redis_pool(app)

# CORS Configuration - restrict to specific origins
CORS(app, 
     origins=app.config['ALLOWED_ORIGINS'],
     supports_credentials=True,
     methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
     allow_headers=['Content-Type', 'Authorization'])

# Rate Limiting - using Redis as storage. The limiter instance lives in
# src/extensions.py so blueprints can decorate their views with stricter
# per-endpoint limits at import time (see src/routes/auth.py).
limiter.init_app(app)

configure_logging(app)


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
app.register_blueprint(characters_bp)
app.register_blueprint(servers_bp)
app.register_blueprint(site_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(claims_bp)
app.register_blueprint(rewards_bp)
app.register_blueprint(boxes_bp)
app.register_blueprint(inventory_bp)
app.register_blueprint(invitations_bp)
app.register_blueprint(notifications_bp)
app.register_blueprint(reports_bp)


@app.route('/')
def index():
    """API root endpoint"""
    return jsonify({
        'name': 'Project Safezone API',
        'version': Config.APP_VERSION,
        'endpoints': {
            'health': '/health',
            'auth': {
                'signin': '/api/auth/signin',
                'signup': '/api/auth/signup',
                'me': '/api/auth/me',
                'password': '/api/auth/password'
            },
            'claims': '/api/claims',
            'invitations': '/api/invitations',
            'notifications': '/api/notifications',
            'reports': '/api/reports',
            'characters': '/api/characters',
            'servers': '/api/servers',
            'boxes': '/api/boxes',
            'inventory': '/api/inventory',
            'admin': {
                'users': '/api/admin/users',
                'servers': '/api/admin/servers',
                'claims': '/api/admin/claims',
                'rewards': '/api/admin/rewards',
                'box_pools': '/api/admin/box-pools',
                'actions': '/api/admin/actions',
                'give': '/api/admin/give',
                'tasks': '/api/admin/tasks',
                'audit': '/api/admin/audit'
            }
        }
    })


@app.route('/health')
def health():
    """Health check endpoint"""
    status = {
        'status': 'healthy',
        'version': Config.APP_VERSION,
        'database': 'disconnected',
        'cache': 'disconnected',
        'game_server': 'unknown'
    }

    # Check database. `get_db()` yields a SQLAlchemy Session, not a DBAPI
    # connection - this asked it for a `cursor()`, which it does not have, so
    # the probe raised AttributeError every time and the check reported a
    # perfectly healthy database as disconnected.
    try:
        with db.get_db() as session:
            session.execute(text('SELECT 1')).fetchone()
            status['database'] = 'connected'
    except Exception as e:
        logger.error(f"Database health check error: {e}")
        status['database'] = 'disconnected'
    
    # Check Redis
    r = get_redis_connection()
    if r:
        try:
            r.ping()
            status['cache'] = 'connected'
        except redis.RedisError as e:
            logger.error(f"Redis error in health check: {e}")

    # Check the game-server manager.
    #
    # This used to read a Redis key called `game_server_status` that nothing in
    # the codebase ever writes, so the answer was permanently 'unknown' - a
    # field that could never say anything. Ask the service instead: listing
    # servers exercises reachability, the shared token and the manager's own
    # database in one call, which is what "is it up" actually means here.
    #
    # Short timeout on purpose: /health is polled, and a hanging dependency
    # must not make the health check itself look hung.
    payload, gs_status = gs_request('GET', '/api/servers', timeout=3)
    if gs_status == 200:
        status['game_server'] = 'connected'
    elif gs_status in (401, 403):
        # Worth distinguishing: this is a token mismatch between the services,
        # not an outage, and it is otherwise a maddening thing to diagnose.
        status['game_server'] = 'unauthorized'
    elif gs_status == 503:
        status['game_server'] = 'unreachable'
    else:
        status['game_server'] = 'error'
        logger.error(f"Game-server health check returned {gs_status}: "
                     f"{payload.get('error') if isinstance(payload, dict) else payload}")
    
    # A service that cannot reach its database is not healthy, whatever the
    # other checks say. Reporting 'healthy' regardless made the field useless -
    # nothing could ever read it and learn anything.
    if status['database'] != 'connected':
        status['status'] = 'degraded'

    return jsonify(status)


if __name__ == '__main__':
    # Initialize database
    try:
        db.init_db()
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
    
    app.run(host='0.0.0.0', port=5000, debug=app.config['FLASK_DEBUG'])

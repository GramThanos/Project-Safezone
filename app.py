"""
Flask web application for Project Safehouse - Project Zomboid Server Manager
"""
import os
from flask import Flask, render_template, jsonify
import redis
import psycopg2

app = Flask(__name__)

# Configuration from environment variables
app.config['DATABASE_HOST'] = os.getenv('DATABASE_HOST', 'db')
app.config['DATABASE_NAME'] = os.getenv('DATABASE_NAME', 'safehouse')
app.config['DATABASE_USER'] = os.getenv('DATABASE_USER', 'safehouse')
app.config['DATABASE_PASSWORD'] = os.getenv('DATABASE_PASSWORD', 'safehouse')
app.config['REDIS_HOST'] = os.getenv('REDIS_HOST', 'cache')
app.config['REDIS_PORT'] = int(os.getenv('REDIS_PORT', '6379'))


def get_db_connection():
    """Get database connection"""
    try:
        conn = psycopg2.connect(
            host=app.config['DATABASE_HOST'],
            database=app.config['DATABASE_NAME'],
            user=app.config['DATABASE_USER'],
            password=app.config['DATABASE_PASSWORD']
        )
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        return None


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
    """Main dashboard page"""
    return render_template('index.html')


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
    conn = get_db_connection()
    if conn:
        status['database'] = 'connected'
        conn.close()
    
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


@app.route('/api/server/status')
def server_status():
    """Get game server status"""
    r = get_redis_connection()
    if not r:
        return jsonify({'error': 'Cache not available'}), 503
    
    try:
        status = r.get('game_server_status') or 'offline'
        return jsonify({
            'status': status,
            'last_update': r.get('game_server_last_update') or 'never'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(host='0.0.0.0', port=5000, debug=debug_mode)

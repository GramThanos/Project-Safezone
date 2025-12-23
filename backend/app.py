import os
from flask import Flask, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Database configuration for MariaDB
db_host = os.getenv('DB_HOST', 'localhost')
db_port = os.getenv('DB_PORT', '3306')
db_name = os.getenv('DB_NAME', 'safehouse')
db_user = os.getenv('DB_USER', 'safehouse_user')
db_password = os.getenv('DB_PASSWORD', 'safehouse_pass')

app.config['SQLALCHEMY_DATABASE_URI'] = f'mysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key')

# Initialize database
db = SQLAlchemy(app)

# Example model for Project Zomboid server
class Server(db.Model):
    __tablename__ = 'servers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='stopped')
    port = db.Column(db.Integer)
    max_players = db.Column(db.Integer, default=32)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'status': self.status,
            'port': self.port,
            'max_players': self.max_players,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

# Routes
@app.route('/')
def index():
    return jsonify({
        'message': 'Project Safehouse API',
        'version': '1.0.0'
    })

@app.route('/api/health')
def health():
    try:
        # Test database connection
        db.session.execute(db.text('SELECT 1'))
        db_status = 'connected'
    except Exception as e:
        db_status = f'error: {str(e)}'
    
    return jsonify({
        'status': 'healthy',
        'database': db_status
    })

@app.route('/api/servers', methods=['GET'])
def get_servers():
    try:
        servers = Server.query.all()
        return jsonify({
            'servers': [server.to_dict() for server in servers]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Create tables on startup
with app.app_context():
    try:
        db.create_all()
        print("Database tables created successfully")
    except Exception as e:
        print(f"Error creating database tables: {e}")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

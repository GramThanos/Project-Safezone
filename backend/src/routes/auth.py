"""Authentication routes"""
import logging
from flask import Blueprint, request, jsonify
from sqlalchemy.exc import IntegrityError
from src.database import db
from src.models.user import User
from src.middleware.auth import generate_token

logger = logging.getLogger(__name__)
auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')


@auth_bp.route('/signin', methods=['POST'])
def signin():
    """User sign in endpoint"""
    data = request.get_json()
    
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({'error': 'Username and password required'}), 400
    
    username = data['username']
    password = data['password']
    
    try:
        with db.get_db() as session:
            user = session.query(User).filter_by(username=username).first()
            
            if not user or not user.check_password(password):
                return jsonify({'error': 'Invalid username or password'}), 401
            
            if user.is_banned():
                return jsonify({'error': 'Account is banned'}), 403
            
            # Generate token
            token = generate_token(user.id, user.username, user.role)
            
            return jsonify({
                'token': token,
                'user': user.to_dict()
            }), 200
    
    except Exception as e:
        logger.error(f"Sign in error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/signup', methods=['POST'])
def signup():
    """User sign up endpoint"""
    data = request.get_json()
    
    if not data or not data.get('username') or not data.get('email') or not data.get('password'):
        return jsonify({'error': 'Username, email, and password required'}), 400
    
    username = data['username']
    email = data['email']
    password = data['password']
    
    try:
        with db.get_db() as session:
            # Check if username or email already exists
            if session.query(User).filter_by(username=username).first():
                return jsonify({'error': 'Username already exists'}), 400
            
            if session.query(User).filter_by(email=email).first():
                return jsonify({'error': 'Email already exists'}), 400
            
            # Create new user
            user = User(username=username, email=email, role=User.ROLE_PLAYER)
            user.set_password(password)
            session.add(user)
            session.flush()  # Flush to get the user ID
            
            # Generate token
            token = generate_token(user.id, user.username, user.role)
            
            return jsonify({
                'token': token,
                'user': user.to_dict()
            }), 201
    
    except Exception as e:
        logger.error(f"Sign up error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/me', methods=['GET'])
def get_current_user():
    """Get current user info from token"""
    from src.middleware.auth import token_required
    
    @token_required
    def _get_user(current_user):
        try:
            with db.get_db() as session:
                user = session.query(User).filter_by(id=current_user['user_id']).first()
                if user:
                    return jsonify({'user': user.to_dict()}), 200
                return jsonify({'error': 'User not found'}), 404
        except Exception as e:
            logger.error(f"Get user error: {e}")
            return jsonify({'error': 'Internal server error'}), 500
    
    return _get_user()

"""Authentication utilities"""
import jwt
import uuid
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify, current_app


def generate_token(user_id, username, role):
    """Generate lightweight JWT token for user with security claims"""
    payload = {
        'user_id': user_id,
        'username': username,
        'role': role,
        'exp': datetime.utcnow() + timedelta(hours=current_app.config['TOKEN_EXPIRY_HOURS']),
        'iat': datetime.utcnow(),  # Issued at
        'iss': current_app.config['TOKEN_ISSUER'],  # Issuer
        'aud': current_app.config['TOKEN_AUDIENCE'],  # Audience
        'jti': str(uuid.uuid4())  # JWT ID for token revocation
    }
    token = jwt.encode(payload, current_app.config['SECRET_KEY'], algorithm='HS256')
    return token


def decode_token(token):
    """Decode and verify JWT token with security validations"""
    try:
        payload = jwt.decode(
            token, 
            current_app.config['SECRET_KEY'], 
            algorithms=['HS256'],
            audience=current_app.config['TOKEN_AUDIENCE'],
            issuer=current_app.config['TOKEN_ISSUER'],
            options={
                'verify_exp': True,
                'verify_iat': True,
                'verify_iss': True,
                'verify_aud': True
            }
        )
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def token_required(f):
    """Decorator to require valid JWT token"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # Get token from Authorization header
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                # Expect format: Bearer <token>
                parts = auth_header.split(' ')
                if len(parts) != 2 or parts[0].lower() != 'bearer':
                    return jsonify({'error': 'Invalid token format'}), 401
                token = parts[1]
            except (IndexError, AttributeError):
                return jsonify({'error': 'Invalid token format'}), 401
        
        if not token:
            return jsonify({'error': 'Token is missing'}), 401
        
        # Decode token
        payload = decode_token(token)
        if not payload:
            return jsonify({'error': 'Token is invalid or expired'}), 401
        
        # Verify required claims
        if not all(k in payload for k in ['user_id', 'username', 'role']):
            return jsonify({'error': 'Invalid token payload'}), 401
        
        # Pass user info to the route
        return f(current_user=payload, *args, **kwargs)
    
    return decorated


def admin_required(f):
    """Decorator to require admin role"""
    @wraps(f)
    @token_required
    def decorated(current_user, *args, **kwargs):
        if current_user['role'] != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        return f(current_user=current_user, *args, **kwargs)
    
    return decorated


def moderator_required(f):
    """Decorator to require moderator or admin role"""
    @wraps(f)
    @token_required
    def decorated(current_user, *args, **kwargs):
        if current_user['role'] not in ['moderator', 'admin']:
            return jsonify({'error': 'Moderator or admin access required'}), 403
        return f(current_user=current_user, *args, **kwargs)
    
    return decorated

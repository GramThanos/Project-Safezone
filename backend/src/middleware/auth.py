"""Authentication utilities"""
import jwt
import logging
import uuid
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify, current_app

logger = logging.getLogger(__name__)


# Endpoints an account with `must_change_password` may still reach: it has to be
# able to see who it is and to set a new password. Everything else is refused
# until it does.
PASSWORD_CHANGE_EXEMPT = {'auth.get_current_user', 'auth.change_password'}

# An appeal process a banned person cannot reach is not an appeal process. These
# endpoints stay open to a banned account; `routes/reports.py` then restricts
# such a caller to appeals only, so this cannot become a way to keep reporting
# other people from behind a ban.
BANNED_ALLOWED = {
    'auth.get_current_user',
    'auth.logout_everywhere',
    # Their ban notification carries the reason and how long it lasts. Telling
    # somebody they are banned and then hiding why would be worse than useless.
    'notifications.list_notifications',
    'notifications.unread_count',
    'notifications.mark_read',
    'notifications.mark_all_read',
    'reports.list_mine',
    'reports.create_report',
}


def generate_token(user_id, username, role, token_version=0):
    """
    Generate lightweight JWT token for user with security claims.
    Must be called within Flask application context (e.g., request handler).
    """
    payload = {
        'user_id': user_id,
        'username': username,
        'role': role,
        # Bumped on the user record to invalidate every outstanding token at
        # once; compared on each request in _apply_live_authorisation.
        'tv': token_version or 0,
        'exp': datetime.utcnow() + timedelta(hours=current_app.config['TOKEN_EXPIRY_HOURS']),
        'iat': datetime.utcnow(),  # Issued at
        'iss': current_app.config['TOKEN_ISSUER'],  # Issuer
        'aud': current_app.config['TOKEN_AUDIENCE'],  # Audience
        'jti': str(uuid.uuid4())  # JWT ID for token revocation
    }
    token = jwt.encode(payload, current_app.config['SECRET_KEY'], algorithm='HS256')
    return token


def decode_token(token):
    """
    Decode and verify JWT token with security validations.
    Must be called within Flask application context (e.g., request handler).
    """
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

        # Authorisation comes from the database, not from the token. Tokens live
        # for hours, so trusting their `role` claim would let a banned or demoted
        # account keep its old access until the token happened to expire.
        error = _apply_live_authorisation(payload)
        if error:
            return error

        # Pass user info to the route
        return f(current_user=payload, *args, **kwargs)

    return decorated


def current_user_optional():
    """The signed-in user for this request, or None.

    For endpoints that are public but show more to somebody signed in. Anything
    wrong with the token - missing, malformed, expired, revoked, banned - is the
    same answer, None, because the caller's question is "who is this?" and not
    "may they proceed": there is nothing to refuse on a page anonymous visitors
    are welcome to read.
    """
    header = request.headers.get('Authorization', '')
    parts = header.split(' ')
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        return None

    payload = decode_token(parts[1])
    if not payload or not all(k in payload for k in ['user_id', 'username', 'role']):
        return None

    # Same live check as `token_required`, so a banned or signed-out account
    # does not keep privileged sight of a public page until its token expires.
    if _apply_live_authorisation(payload) is not None:
        return None
    return payload


def _apply_live_authorisation(payload):
    """Refresh a token payload from the user record, or return an error response.

    Overwrites `role`/`username` with the stored values and rejects accounts that
    have since been banned or deleted. Returns None when the request may proceed.
    """
    # Imported here to keep this module importable without the app/db wiring.
    from src.database import db
    from src.models.user import User

    try:
        with db.get_db() as session:
            user = session.query(User).filter_by(id=payload['user_id']).first()
            if not user:
                return jsonify({'error': 'Account no longer exists'}), 401
            if user.is_banned() and request.endpoint not in BANNED_ALLOWED:
                return jsonify({'error': 'Account is banned'}), 403

            # A token minted before the account's version was bumped is dead:
            # the password changed, or somebody signed out everywhere.
            if int(payload.get('tv', 0)) != int(user.token_version or 0):
                return jsonify({'error': 'Session has ended, please sign in again'}), 401

            # A forced password change blocks everything except reading your own
            # account and setting the new password.
            if user.must_change_password and request.endpoint not in PASSWORD_CHANGE_EXEMPT:
                return jsonify({
                    'error': 'You must change your password before continuing',
                    'code': 'password_change_required'
                }), 403

            payload['role'] = user.role
            payload['username'] = user.username
            payload['must_change_password'] = bool(user.must_change_password)
            payload['email_verified'] = bool(user.email_verified)
    except Exception as e:
        logger.error(f"Authorisation lookup failed: {e}")
        return jsonify({'error': 'Internal server error'}), 500
    return None


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

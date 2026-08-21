"""Authentication and account lifecycle.

Registration is controllable: it can be closed outright, gated behind a shared
password, or opened to invitation links - and those are independent switches
rather than one mode, so an operator can combine them. See
`src/utils/settings.py`.
"""
import hmac
import logging
import re
from datetime import datetime

from flask import Blueprint, request, jsonify, current_app

from src.database import db
from src.extensions import limiter
from src.middleware.auth import generate_token, token_required
from src.models.user import User
from src.models.auth_token import AuthToken, hash_token
from src.models.invitation import Invitation, hash_code
from src.models.character import Character
from src.models.claim_request import ClaimRequest
from src.models.user_box import UserBox
from src.models.inventory_item import InventoryItem
from src.models.audit_log import AuditLog
from src.utils import audit, captcha, mailer, settings, alerting

logger = logging.getLogger(__name__)
auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

# Deliberately permissive: the confirmation mail is what actually establishes
# that an address works. This only rejects input that cannot be an address.
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$')

MIN_PASSWORD_LENGTH = 8


def normalize_email(raw):
    """Addresses are compared case-insensitively, so store them that way."""
    return (raw or '').strip().lower()


def _issue_token(user):
    return generate_token(user.id, user.username, user.role, user.token_version)


def _send_verification(session, user):
    """Mint a verification token for `user` and mail it. Never raises."""
    row, plaintext = AuthToken.issue(user.id, AuthToken.PURPOSE_VERIFY)
    session.add(row)
    try:
        mailer.send_verification(user.email, user.username, plaintext)
    except Exception as e:  # pragma: no cover - mailer already swallows its own
        logger.error(f"Verification mail failed for user {user.id}: {e}")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

@auth_bp.route('/captcha', methods=['GET'])
@limiter.limit(lambda: current_app.config['RATELIMIT_SIGNUP_CAPTCHA'])
def get_captcha():
    """Issue a challenge for the sign-up form."""
    if not captcha.is_enabled():
        return jsonify({'enabled': False}), 200
    issued = captcha.issue()
    if not issued:
        return jsonify({'error': 'Could not create a challenge, try again'}), 503
    challenge_id, svg = issued
    return jsonify({'enabled': True, 'id': challenge_id, 'image': svg}), 200


@auth_bp.route('/registration', methods=['GET'])
def registration_status():
    """What the sign-up form should ask for, before anyone types anything."""
    try:
        return jsonify({
            'enabled': bool(settings.get('registration_enabled')),
            'password_required': bool(settings.get('registration_password')),
            'invites_enabled': bool(settings.get('invites_enabled')),
            'captcha_required': captcha.is_enabled(),
        }), 200
    except Exception as e:
        logger.error(f"Registration status error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


def _resolve_invitation(session, code):
    """Return ``(invitation, error)`` for a supplied invitation code."""
    if not code:
        return None, None
    if not settings.get('invites_enabled'):
        return None, 'Invitations are not being accepted'
    invitation = (session.query(Invitation)
                  .filter_by(code_hash=hash_code(code.strip()))
                  .first())
    if not invitation or not invitation.is_usable():
        # One message for every failure: a caller should not be able to probe
        # which codes exist by reading the difference.
        return None, 'That invitation link is not valid'
    return invitation, None


@auth_bp.route('/signup', methods=['POST'])
@limiter.limit(lambda: current_app.config['RATELIMIT_SIGNUP'])
def signup():
    """Create an account, subject to whatever registration gate is configured."""
    data = request.get_json() or {}

    username = (data.get('username') or '').strip()
    email = normalize_email(data.get('email'))
    password = data.get('password') or ''

    if not username or not email or not password:
        return jsonify({'error': 'Username, email, and password required'}), 400
    if len(username) < 3 or len(username) > 80:
        return jsonify({'error': 'Username must be between 3 and 80 characters'}), 400
    if not EMAIL_RE.match(email) or len(email) > 120:
        return jsonify({'error': 'That does not look like an email address'}), 400
    if len(password) < MIN_PASSWORD_LENGTH:
        return jsonify({'error': f'Password must be at least {MIN_PASSWORD_LENGTH} characters'}), 400

    # Checked before anything touches the database, so a bot cannot use signup
    # as a free username-availability oracle.
    if captcha.is_enabled():
        if not captcha.verify(data.get('captcha_id'), data.get('captcha_answer')):
            return jsonify({
                'error': 'That code was not right. Try the new one.',
                'code': 'captcha_failed'
            }), 400

    try:
        with db.get_db() as session:
            invitation, invite_error = _resolve_invitation(session, data.get('invite_code'))
            if invite_error:
                return jsonify({'error': invite_error}), 403

            if not invitation:
                # No invitation, so the open-registration rules apply.
                if not settings.get('registration_enabled'):
                    return jsonify({'error': 'Registration is currently closed'}), 403

                required = settings.get('registration_password') or ''
                if required:
                    supplied = data.get('registration_password') or ''
                    if not hmac.compare_digest(str(required), str(supplied)):
                        return jsonify({'error': 'That registration password is not correct'}), 403

            if session.query(User).filter_by(username=username).first():
                return jsonify({'error': 'Username already exists'}), 400
            if session.query(User).filter_by(email=email).first():
                return jsonify({'error': 'Email already exists'}), 400

            user = User(username=username, email=email, role=User.ROLE_PLAYER,
                        invited_by=invitation.created_by if invitation else None)
            user.set_password(password)
            # set_password bumps token_version on principle; a brand-new account
            # starts from zero so its first token matches.
            user.token_version = 0
            user.must_change_password = False
            session.add(user)
            session.flush()

            if invitation:
                invitation.uses = (invitation.uses or 0) + 1

            _send_verification(session, user)
            # The username, and how they got in. Not the email address - an
            # alert channel is not a place to publish somebody's contact
            # details, and nothing in a "welcome" message needs it.
            alerting.emit('user.signup', f'{username} signed up',
                          fields=[('Account', username),
                                  ('Via', 'invitation' if invitation else 'open registration')])

            return jsonify({
                'token': _issue_token(user),
                'user': user.to_dict(),
                'verification_sent': True
            }), 201
    except Exception as e:
        logger.error(f"Sign up error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@auth_bp.route('/signin', methods=['POST'])
@limiter.limit(lambda: current_app.config['RATELIMIT_SIGNIN'])
def signin():
    """Exchange credentials for a token."""
    data = request.get_json() or {}
    identifier = (data.get('username') or '').strip()
    password = data.get('password') or ''

    if not identifier or not password:
        return jsonify({'error': 'Username and password required'}), 400

    try:
        with db.get_db() as session:
            user = session.query(User).filter_by(username=identifier).first()
            if not user:
                # Accept the email address too - people forget which they used.
                user = session.query(User).filter_by(email=normalize_email(identifier)).first()

            if not user or not user.check_password(password):
                return jsonify({'error': 'Invalid credentials'}), 401

            # A banned account *does* get a token. Refusing one here would make
            # the appeal process unreachable by the only people who need it -
            # the middleware still refuses a banned caller everywhere except
            # their own account and the appeal endpoints.
            payload = {
                'token': _issue_token(user),
                'user': user.to_dict()
            }
            if user.is_banned():
                payload['banned'] = True
                payload['message'] = ('This account is banned. You can still '
                                      'read your notifications and appeal.')
            return jsonify(payload), 200
    except Exception as e:
        logger.error(f"Sign in error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/me', methods=['GET'])
@token_required
def get_current_user(current_user):
    """The signed-in account, plus the ban being served if there is one.

    A banned player is told to appeal without being shown what they are
    appealing, which makes for appeals that answer the wrong accusation - and
    somebody is entitled to know why they were banned and whether it ends.
    """
    from src.models.ban import Ban

    try:
        with db.get_db() as session:
            user = session.query(User).filter_by(id=current_user['user_id']).first()
            if not user:
                return jsonify({'error': 'User not found'}), 404

            payload = user.to_dict()
            if user.is_banned():
                ban = (session.query(Ban)
                       .filter_by(user_id=user.id)
                       .filter(Ban.lifted_at.is_(None))
                       .order_by(Ban.created_at.desc())
                       .first())
                if ban:
                    # Only what the person needs: why, and until when. Who
                    # issued it is staff information.
                    payload['ban'] = {
                        'reason': ban.reason,
                        'expires_at': ban.expires_at.isoformat() if ban.expires_at else None,
                        'permanent': ban.expires_at is None,
                        'created_at': ban.created_at.isoformat() if ban.created_at else None,
                    }
            return jsonify({'user': payload}), 200
    except Exception as e:
        logger.error(f"Get current user error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/logout-all', methods=['POST'])
@token_required
def logout_everywhere(current_user):
    """Invalidate every outstanding token for this account, including this one."""
    try:
        with db.get_db() as session:
            user = session.query(User).filter_by(id=current_user['user_id']).first()
            if not user:
                return jsonify({'error': 'User not found'}), 404
            user.token_version = (user.token_version or 0) + 1
            return jsonify({'message': 'Signed out everywhere'}), 200
    except Exception as e:
        logger.error(f"Logout-all error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

@auth_bp.route('/password', methods=['PUT'])
@limiter.limit(lambda: current_app.config['RATELIMIT_PASSWORD'])
def change_password():
    """Change the password, given the current one."""
    @token_required
    def _change(current_user):
        data = request.get_json() or {}
        current_password = data.get('current_password')
        new_password = data.get('new_password')

        if not current_password or not new_password:
            return jsonify({'error': 'Current and new password are required'}), 400
        if len(new_password) < MIN_PASSWORD_LENGTH:
            return jsonify({'error': f'New password must be at least {MIN_PASSWORD_LENGTH} characters'}), 400

        try:
            with db.get_db() as session:
                user = session.query(User).filter_by(id=current_user['user_id']).first()
                if not user:
                    return jsonify({'error': 'User not found'}), 404
                if not user.check_password(current_password):
                    return jsonify({'error': 'Current password is incorrect'}), 401

                user.set_password(new_password)  # also bumps token_version
                session.flush()

                # Every other session just died, including this browser's token.
                # Hand back a fresh one so the user is not logged out mid-action.
                return jsonify({
                    'message': 'Password updated. Other sessions have been signed out.',
                    'token': _issue_token(user),
                    'user': user.to_dict()
                }), 200
        except Exception as e:
            logger.error(f"Change password error: {e}")
            return jsonify({'error': 'Internal server error'}), 500

    return _change()


@auth_bp.route('/password/forgot', methods=['POST'])
@limiter.limit(lambda: current_app.config['RATELIMIT_PASSWORD_RESET'])
def forgot_password():
    """Start a password reset.

    Always answers the same way. Reporting whether an address is registered
    would turn this into an account-enumeration oracle, which matters more on an
    open-signup deployment than the small convenience of a clearer message.
    """
    data = request.get_json() or {}
    email = normalize_email(data.get('email'))
    generic = jsonify({
        'message': 'If that address has an account, a reset link is on its way.'
    }), 200

    if not email:
        return generic

    try:
        with db.get_db() as session:
            user = session.query(User).filter_by(email=email).first()
            if not user or user.is_banned():
                return generic

            row, plaintext = AuthToken.issue(user.id, AuthToken.PURPOSE_RESET)
            session.add(row)
            mailer.send_password_reset(user.email, user.username, plaintext)
            return generic
    except Exception as e:
        logger.error(f"Forgot password error: {e}")
        return generic


@auth_bp.route('/password/reset', methods=['POST'])
@limiter.limit(lambda: current_app.config['RATELIMIT_PASSWORD_RESET'])
def reset_password():
    """Complete a password reset using a mailed token."""
    data = request.get_json() or {}
    token = (data.get('token') or '').strip()
    new_password = data.get('new_password') or ''

    if not token or not new_password:
        return jsonify({'error': 'Token and new password are required'}), 400
    if len(new_password) < MIN_PASSWORD_LENGTH:
        return jsonify({'error': f'Password must be at least {MIN_PASSWORD_LENGTH} characters'}), 400

    try:
        with db.get_db() as session:
            row = (session.query(AuthToken)
                   .filter_by(token_hash=hash_token(token),
                              purpose=AuthToken.PURPOSE_RESET)
                   .first())
            if not row or not row.is_usable():
                return jsonify({'error': 'That reset link is expired or already used'}), 400

            user = session.query(User).filter_by(id=row.user_id).first()
            if not user:
                return jsonify({'error': 'Account no longer exists'}), 404

            user.set_password(new_password)  # bumps token_version
            row.used_at = datetime.utcnow()

            # Reaching the mailbox proves the address, so stop nagging about it.
            user.email_verified = True

            audit.record(session, None, 'password.reset',
                         target=f'user:{user.id}',
                         detail=f"{user.username} reset their password by email")
            session.flush()

            return jsonify({
                'message': 'Password updated. You can sign in now.',
                'token': _issue_token(user),
                'user': user.to_dict()
            }), 200
    except Exception as e:
        logger.error(f"Reset password error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# Email address
# ---------------------------------------------------------------------------

@auth_bp.route('/verify/request', methods=['POST'])
@limiter.limit(lambda: current_app.config['RATELIMIT_PASSWORD_RESET'])
def request_verification():
    """Send (or resend) the confirmation mail for the signed-in account."""
    @token_required
    def _request(current_user):
        try:
            with db.get_db() as session:
                user = session.query(User).filter_by(id=current_user['user_id']).first()
                if not user:
                    return jsonify({'error': 'User not found'}), 404
                if user.email_verified:
                    return jsonify({'message': 'That address is already confirmed'}), 200
                _send_verification(session, user)
                return jsonify({'message': 'Confirmation sent'}), 200
        except Exception as e:
            logger.error(f"Request verification error: {e}")
            return jsonify({'error': 'Internal server error'}), 500

    return _request()


@auth_bp.route('/verify', methods=['POST'])
def verify_email():
    """Confirm an address with a mailed token. Deliberately needs no session."""
    data = request.get_json() or {}
    token = (data.get('token') or '').strip()
    if not token:
        return jsonify({'error': 'A token is required'}), 400

    try:
        with db.get_db() as session:
            row = (session.query(AuthToken)
                   .filter_by(token_hash=hash_token(token),
                              purpose=AuthToken.PURPOSE_VERIFY)
                   .first())
            if not row or not row.is_usable():
                return jsonify({'error': 'That confirmation link is expired or already used'}), 400

            user = session.query(User).filter_by(id=row.user_id).first()
            if not user:
                return jsonify({'error': 'Account no longer exists'}), 404

            user.email_verified = True
            row.used_at = datetime.utcnow()
            return jsonify({'message': 'Address confirmed'}), 200
    except Exception as e:
        logger.error(f"Verify email error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/email', methods=['PUT'])
@limiter.limit(lambda: current_app.config['RATELIMIT_PASSWORD'])
def change_email():
    """Change the address, re-confirming the new one.

    The username is deliberately not changeable: it is the display identity
    across claims, the audit log and in-game links.
    """
    @token_required
    def _change(current_user):
        data = request.get_json() or {}
        password = data.get('password') or ''
        email = normalize_email(data.get('email'))

        if not password or not email:
            return jsonify({'error': 'Password and new email are required'}), 400
        if not EMAIL_RE.match(email) or len(email) > 120:
            return jsonify({'error': 'That does not look like an email address'}), 400

        try:
            with db.get_db() as session:
                user = session.query(User).filter_by(id=current_user['user_id']).first()
                if not user:
                    return jsonify({'error': 'User not found'}), 404
                if not user.check_password(password):
                    return jsonify({'error': 'Password is incorrect'}), 401
                if email == user.email:
                    return jsonify({'error': 'That is already your address'}), 400

                taken = session.query(User).filter_by(email=email).first()
                if taken:
                    return jsonify({'error': 'Email already exists'}), 400

                user.email = email
                user.email_verified = False
                session.flush()
                _send_verification(session, user)

                return jsonify({
                    'message': 'Address changed. Check the new inbox to confirm it.',
                    'user': user.to_dict()
                }), 200
        except Exception as e:
            logger.error(f"Change email error: {e}")
            return jsonify({'error': 'Internal server error'}), 500

    return _change()


# ---------------------------------------------------------------------------
# The account itself
# ---------------------------------------------------------------------------

@auth_bp.route('/export', methods=['GET'])
@token_required
def export_account(current_user):
    """Everything held about the signed-in account, as JSON."""
    user_id = current_user['user_id']
    try:
        with db.get_db() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if not user:
                return jsonify({'error': 'User not found'}), 404

            characters = session.query(Character).filter_by(user_id=user_id).all()
            claims = session.query(ClaimRequest).filter_by(user_id=user_id).all()
            boxes = session.query(UserBox).filter_by(user_id=user_id).all()
            items = session.query(InventoryItem).filter_by(user_id=user_id).all()
            actions = (session.query(AuditLog)
                       .filter_by(actor_user_id=user_id)
                       .order_by(AuditLog.created_at.asc())
                       .all())

            return jsonify({
                'exported_at': datetime.utcnow().isoformat(),
                'account': user.to_dict(),
                'characters': [c.to_dict() for c in characters],
                'claims': [c.to_dict() for c in claims],
                'loot_boxes': [b.to_dict() for b in boxes],
                'inventory': [i.to_dict() for i in items],
                'actions': [
                    {
                        'action': a.action,
                        'target': a.target,
                        'detail': a.detail,
                        'created_at': a.created_at.isoformat() if a.created_at else None,
                    }
                    for a in actions
                ],
            }), 200
    except Exception as e:
        logger.error(f"Export account error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/me', methods=['DELETE'])
@limiter.limit(lambda: current_app.config['RATELIMIT_PASSWORD'])
def delete_account():
    """Close the account permanently, re-authenticating first."""
    @token_required
    def _delete(current_user):
        data = request.get_json() or {}
        password = data.get('password') or ''
        if not password:
            return jsonify({'error': 'Your password is required to close the account'}), 400

        try:
            with db.get_db() as session:
                user = session.query(User).filter_by(id=current_user['user_id']).first()
                if not user:
                    return jsonify({'error': 'User not found'}), 404
                if not user.check_password(password):
                    return jsonify({'error': 'Password is incorrect'}), 401

                # Deleting the account releases its in-game names, the same way
                # an unlink does - otherwise a departed player holds a name for
                # good. Characters cascade from the user row; this records what
                # was released before they go.
                characters = session.query(Character).filter_by(user_id=user.id).all()
                released = [f"{c.in_game_username}@server{c.server_id}"
                            for c in characters if c.verified and c.in_game_username]

                username = user.username
                audit.record(session, None, 'account.delete',
                             target=f'user:{user.id}',
                             detail=f"{username} closed their account"
                                    + (f"; released {', '.join(released)}" if released else ''))

                session.delete(user)
                return jsonify({'message': 'Account closed'}), 200
        except Exception as e:
            logger.error(f"Delete account error: {e}")
            return jsonify({'error': 'Internal server error'}), 500

    return _delete()

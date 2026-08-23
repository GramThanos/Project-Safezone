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
from sqlalchemy import or_

from src.database import db
from src.middleware.auth import (generate_token, token_required,
                                 generate_mfa_challenge_token,
                                 decode_mfa_challenge_token)
from src.models.user import User
from src.models.auth_token import AuthToken, hash_token
from src.models.invitation import Invitation, hash_code
from src.models.character import Character
from src.models.claim_request import ClaimRequest
from src.models.user_box import UserBox
from src.models.inventory_item import InventoryItem
from src.models.audit_log import AuditLog
from src.utils import audit, captcha, mailer, settings, alerting, totp

logger = logging.getLogger(__name__)
auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

# Deliberately permissive: the confirmation mail is what actually establishes
# that an address works. This only rejects input that cannot be an address.
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$')

# The username is the account's display identity: it appears in the audit log,
# in staff notifications, in the alert titles that reach a Discord channel, and
# it is deliberately immutable once chosen (see `change_email`). That makes its
# contents load-bearing, so the character set is pinned rather than only the
# length.
#
# What this shuts out, in order of how much it mattered:
#   * Impersonation. Zero-width joiners, Cyrillic homoglyphs and RTL overrides
#     let an account render as an existing one - including `admin` - everywhere
#     a name is displayed.
#   * Markdown and mention syntax reaching a staff Discord channel through an
#     alert title, attributed to the site rather than to the person.
#   * CR/LF, which flows into the mail Subject for an alert. Python's email
#     policy refuses such a header, the exception is caught and logged, and the
#     visible result is that staff alert mail silently stops arriving.
#
# Case is not handled here: `users.username` carries the database's default
# collation, which is case-insensitive, so the unique index already refuses
# `Admin` alongside `admin`. A deployment that overrides that to a binary
# collation would need a folded key here instead.
#
# `\Z` and not `$`: Python's `$` also matches immediately before a trailing
# newline, so `^...$` would accept "admin\n". The `.strip()` on the way in makes
# that unreachable here, but the anchor is the part that should not depend on
# it. Same convention as `actions.py` and `mods.py`.
USERNAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{2,79}\Z')

MIN_PASSWORD_LENGTH = 8


def normalize_email(raw):
    """Addresses are compared case-insensitively, so store them that way."""
    return (raw or '').strip().lower()


def _issue_token(user):
    return generate_token(user.id, user.username, user.role, user.token_version)


def _signin_success(user):
    """The body a completed sign-in returns: a session token, and a ban notice
    if one is being served.

    A banned account *does* get a token. Refusing one here would make the appeal
    process unreachable by the only people who need it - the middleware still
    refuses a banned caller everywhere except their own account and the appeal
    endpoints.
    """
    payload = {'token': _issue_token(user), 'user': user.to_dict()}
    if user.is_banned():
        payload['banned'] = True
        payload['message'] = ('This account is banned. You can still '
                              'read your notifications and appeal.')
    return payload


def _totp_issuer():
    """The label an authenticator shows for this account. Follows the site's
    brand name so an operator who renamed the site is not stuck with 'Safezone'
    in every user's phone, and falls back if settings are unreadable."""
    try:
        name = (settings.get('site_brand_name') or '').strip()
    except Exception:
        name = ''
    # Colons separate label from issuer in the otpauth spec, so a brand name
    # containing one would split the label; keep it to a clean token.
    return name.replace(':', ' ') or 'Safezone'


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


INVALID_INVITE = 'That invitation link is not valid'


def _resolve_invitation(session, code):
    """Return ``(invitation, error)`` for a supplied invitation code.

    A read, and only advisory: it rejects an obviously bad code before anything
    expensive happens, but it does not reserve the use. `_claim_invitation` is
    what actually decides, because between this check and the write there is a
    window that two concurrent signups can both pass through.
    """
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
        return None, INVALID_INVITE
    return invitation, None


def _claim_invitation(session, invitation):
    """Consume one use of an invitation. Returns True if it was still available.

    The check and the increment are a single conditional UPDATE, so the database
    decides who gets the last use. Reading `is_usable()` and then writing
    `uses + 1` as two statements let two concurrent signups both observe
    ``uses = 0`` and both write ``uses = 1``, which admitted two accounts on a
    single-use link and made `player_invite_quota` advisory.

    The predicate repeats `Invitation.is_usable()` in SQL rather than calling
    it, because the point is to evaluate it against the row as it is *now*
    rather than as this transaction first read it.

    Must be called before the user row is created: `get_db` commits on normal
    exit, so returning an error after a mutation would persist that mutation.
    """
    matched = (session.query(Invitation)
               .filter(Invitation.id == invitation.id,
                       Invitation.revoked_at.is_(None),
                       Invitation.uses < Invitation.max_uses)
               .filter(or_(Invitation.expires_at.is_(None),
                           Invitation.expires_at > datetime.utcnow()))
               .update({'uses': Invitation.uses + 1}, synchronize_session=False))
    return bool(matched)


@auth_bp.route('/signup', methods=['POST'])
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
    if not USERNAME_RE.match(username):
        return jsonify({
            'error': 'Username may use letters, digits, underscore, dot and '
                     'hyphen, and must start with a letter or digit'
        }), 400
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

            # Claimed before the account is built, not after. Everything below
            # this line is a mutation, and `get_db` commits on normal exit - so
            # a use that turned out to be gone has to be discovered while
            # returning is still free. A later failure rolls the claim back with
            # the rest of the transaction.
            if invitation and not _claim_invitation(session, invitation):
                return jsonify({'error': INVALID_INVITE}), 403

            user = User(username=username, email=email, role=User.ROLE_PLAYER,
                        invited_by=invitation.created_by if invitation else None)
            user.set_password(password)
            # set_password bumps token_version on principle; a brand-new account
            # starts from zero so its first token matches.
            user.token_version = 0
            user.must_change_password = False
            session.add(user)
            session.flush()

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

            # With 2FA on, the password is only the first half. Hand back a
            # short-lived challenge instead of a session; the caller returns it
            # to /signin/2fa alongside a code. Nothing about the account - not
            # even that it is banned - is disclosed until the second factor
            # clears, so this cannot become a way to probe who has 2FA and who
            # does not beyond the fact of the prompt.
            if user.totp_enabled:
                return jsonify({
                    'mfa_required': True,
                    'mfa_token': generate_mfa_challenge_token(user.id)
                }), 200

            return jsonify(_signin_success(user)), 200
    except Exception as e:
        logger.error(f"Sign in error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/signin/2fa', methods=['POST'])
def signin_verify_2fa():
    """Finish a sign-in that owes a second factor.

    Takes the challenge minted by `signin` and a current TOTP code. Deliberately
    no session of its own: the challenge token is the proof the password already
    passed, so this endpoint authenticates on that plus the code and nothing
    else.
    """
    data = request.get_json() or {}
    mfa_token = (data.get('mfa_token') or '').strip()
    code = (data.get('code') or '').strip()

    user_id = decode_mfa_challenge_token(mfa_token)
    if not user_id:
        # Expired or tampered: send them back to the password step rather than
        # letting them sit on a dead challenge guessing codes.
        return jsonify({'error': 'That sign-in expired. Please sign in again.',
                        'code': 'mfa_challenge_expired'}), 401

    try:
        with db.get_db() as session:
            user = session.query(User).filter_by(id=user_id).first()
            # totp_enabled can have been turned off between the two requests;
            # then there is nothing to verify and the challenge is meaningless.
            if not user or not user.totp_enabled or not user.totp_secret:
                return jsonify({'error': 'That sign-in expired. Please sign in again.',
                                'code': 'mfa_challenge_expired'}), 401
            if not totp.verify(user.totp_secret, code):
                return jsonify({'error': 'That code was not right. Try the current one.'}), 401
            return jsonify(_signin_success(user)), 200
    except Exception as e:
        logger.error(f"Sign in 2FA error: {e}")
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
def reset_password():
    """Complete a password reset using a mailed token."""
    data = request.get_json() or {}
    token = (data.get('token') or '').strip()
    new_password = data.get('new_password') or ''
    # Opt-in recovery for a lost authenticator: with the reset link (which
    # proves email control) the person can ask to strip 2FA at the same time.
    # Off by default, so an ordinary reset keeps the second factor.
    clear_2fa = bool(data.get('clear_2fa'))

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

            # Clear 2FA only when explicitly asked, and only as part of this
            # submission - nothing is touched until the link is opened and a new
            # password is set. This is the lost-authenticator path: without it
            # the code lives on a device that is gone. Left unchecked, 2FA
            # survives the reset and still owes a code below.
            if clear_2fa and (user.totp_enabled or user.totp_secret):
                user.totp_enabled = False
                user.totp_secret = None
                audit.record(session, None, '2fa.reset_cleared',
                             target=f'user:{user.id}',
                             detail=f"{user.username} cleared two-factor auth via password reset")
            session.flush()

            # 2FA has to hold here too, or a reset link (which only proves email
            # control) would be a way around the second factor - which is exactly
            # the case it exists to cover. The password is already changed; the
            # session still owes a code (unless it was just cleared above).
            if user.totp_enabled:
                return jsonify({
                    'message': 'Password updated. Enter a code to finish signing in.',
                    'mfa_required': True,
                    'mfa_token': generate_mfa_challenge_token(user.id)
                }), 200

            return jsonify({
                'message': 'Password updated. You can sign in now.',
                'token': _issue_token(user),
                'user': user.to_dict()
            }), 200
    except Exception as e:
        logger.error(f"Reset password error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# Two-factor authentication (TOTP)
# ---------------------------------------------------------------------------

@auth_bp.route('/2fa/setup', methods=['POST'])
@token_required
def setup_2fa(current_user):
    """Begin enabling 2FA: mint a secret and hand back the provisioning URI.

    Gated on the current password, because turning on 2FA is a security change
    and a walk-up attacker on an unlocked, already-signed-in browser should not
    be able to lock the real owner into a factor only the attacker holds.

    The secret is stored now but 2FA stays off until `/2fa/enable` confirms a
    code, which proves the app actually scanned it. Re-running setup before
    confirming just replaces the unused secret.
    """
    data = request.get_json() or {}
    password = data.get('password') or ''
    if not password:
        return jsonify({'error': 'Your password is required'}), 400

    try:
        with db.get_db() as session:
            user = session.query(User).filter_by(id=current_user['user_id']).first()
            if not user:
                return jsonify({'error': 'User not found'}), 404
            if not user.check_password(password):
                return jsonify({'error': 'Password is incorrect'}), 401
            if user.totp_enabled:
                return jsonify({'error': 'Two-factor authentication is already on'}), 400

            secret = totp.generate_secret()
            user.totp_secret = secret
            session.flush()

            return jsonify({
                'secret': secret,
                'otpauth_uri': totp.provisioning_uri(secret, user.username, _totp_issuer()),
            }), 200
    except Exception as e:
        logger.error(f"2FA setup error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/2fa/enable', methods=['POST'])
@token_required
def enable_2fa(current_user):
    """Turn 2FA on, once the app proves it holds the secret with a live code."""
    data = request.get_json() or {}
    code = (data.get('code') or '').strip()
    if not code:
        return jsonify({'error': 'Enter the code from your authenticator'}), 400

    try:
        with db.get_db() as session:
            user = session.query(User).filter_by(id=current_user['user_id']).first()
            if not user:
                return jsonify({'error': 'User not found'}), 404
            if user.totp_enabled:
                return jsonify({'error': 'Two-factor authentication is already on'}), 400
            # No pending secret means setup was never run (or ran on another
            # device); there is nothing to confirm.
            if not user.totp_secret:
                return jsonify({'error': 'Start by setting up two-factor authentication'}), 400
            if not totp.verify(user.totp_secret, code):
                return jsonify({'error': 'That code was not right. Try the current one.'}), 401

            user.totp_enabled = True
            audit.record(session, user.id, '2fa.enabled', target=f'user:{user.id}',
                         detail=f"{user.username} turned on two-factor authentication")
            return jsonify({'message': 'Two-factor authentication is on.',
                            'user': user.to_dict()}), 200
    except Exception as e:
        logger.error(f"2FA enable error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/2fa/disable', methods=['POST'])
@token_required
def disable_2fa(current_user):
    """Turn 2FA off. Needs the password and a current code together.

    Both, because either alone is the sort of thing an attacker on a borrowed
    session might have: the password re-auth stops a walk-up from stripping the
    factor, and requiring a live code proves the person doing it still holds the
    authenticator rather than just the open tab.
    """
    data = request.get_json() or {}
    password = data.get('password') or ''
    code = (data.get('code') or '').strip()
    if not password or not code:
        return jsonify({'error': 'Your password and a current code are required'}), 400

    try:
        with db.get_db() as session:
            user = session.query(User).filter_by(id=current_user['user_id']).first()
            if not user:
                return jsonify({'error': 'User not found'}), 404
            if not user.totp_enabled:
                return jsonify({'error': 'Two-factor authentication is not on'}), 400
            if not user.check_password(password):
                return jsonify({'error': 'Password is incorrect'}), 401
            if not totp.verify(user.totp_secret, code):
                return jsonify({'error': 'That code was not right. Try the current one.'}), 401

            user.totp_enabled = False
            user.totp_secret = None
            audit.record(session, user.id, '2fa.disabled', target=f'user:{user.id}',
                         detail=f"{user.username} turned off two-factor authentication")
            return jsonify({'message': 'Two-factor authentication is off.',
                            'user': user.to_dict()}), 200
    except Exception as e:
        logger.error(f"2FA disable error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# Email address
# ---------------------------------------------------------------------------

@auth_bp.route('/verify/request', methods=['POST'])
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

"""Invitation links.

Staff can always issue them. Ordinary players can too when
`player_invites_enabled` is on, bounded by `player_invite_quota` so one account
cannot mint an unlimited supply. The issuer is recorded on the invited account
either way, because knowing who vouched for someone is the point.
"""
import logging
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify

from src.database import db
from src.models.invitation import Invitation
from src.models.user import User
from src.middleware.auth import token_required
from src.utils import audit, mailer, paging, settings

logger = logging.getLogger(__name__)
invitations_bp = Blueprint('invitations', __name__, url_prefix='/api/invitations')

MAX_USES_CAP = 100
MAX_EXPIRY_DAYS = 365


def _is_staff(current_user):
    return current_user['role'] in (User.ROLE_MODERATOR, User.ROLE_ADMIN)


def _link_for(code):
    base = mailer.site_url()
    return f"{base}/signup?invite={code}"


@invitations_bp.route('', methods=['GET'])
@token_required
def list_invitations(current_user):
    """Staff see every invitation; a player sees only their own."""
    try:
        with db.get_db() as session:
            limit, offset = paging.params()
            query = session.query(Invitation)
            if not _is_staff(current_user):
                query = query.filter_by(created_by=current_user['user_id'])
            query = query.order_by(Invitation.created_at.desc())
            rows, total = paging.page(query, limit, offset)
            return jsonify({
                'invitations': [r.to_dict() for r in rows],
                'pagination': paging.meta(total, limit, offset)
            }), 200
    except Exception as e:
        logger.error(f"List invitations error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@invitations_bp.route('', methods=['POST'])
@token_required
def create_invitation(current_user):
    """Mint an invitation link.

    The code is returned exactly once, here: only its hash is stored, so it
    cannot be shown again later.
    """
    data = request.get_json() or {}
    staff = _is_staff(current_user)

    try:
        with db.get_db() as session:
            if not staff:
                if not settings.get('player_invites_enabled'):
                    return jsonify({'error': 'Players cannot issue invitations'}), 403

                quota = settings.get('player_invite_quota') or 0
                outstanding = [
                    row for row in session.query(Invitation)
                    .filter_by(created_by=current_user['user_id']).all()
                    if row.is_usable()
                ]
                if quota and len(outstanding) >= quota:
                    return jsonify({
                        'error': f'You already have {len(outstanding)} unused invitations '
                                 f'(the limit is {quota})'
                    }), 409

            # Players get one-shot links; letting them set a use count would make
            # the quota meaningless.
            max_uses = 1
            if staff:
                try:
                    max_uses = int(data.get('max_uses', 1) or 1)
                except (TypeError, ValueError):
                    return jsonify({'error': 'max_uses must be a whole number'}), 400
                if max_uses < 1 or max_uses > MAX_USES_CAP:
                    return jsonify({'error': f'max_uses must be between 1 and {MAX_USES_CAP}'}), 400

            expires_at = None
            if data.get('expires_in_days') not in (None, ''):
                try:
                    days = int(data['expires_in_days'])
                except (TypeError, ValueError):
                    return jsonify({'error': 'expires_in_days must be a whole number'}), 400
                if days < 1 or days > MAX_EXPIRY_DAYS:
                    return jsonify({'error': f'expires_in_days must be between 1 and {MAX_EXPIRY_DAYS}'}), 400
                expires_at = datetime.utcnow() + timedelta(days=days)

            note = (data.get('note') or '').strip() or None
            row, code = Invitation.issue(current_user['user_id'], max_uses, expires_at, note)
            session.add(row)
            session.flush()

            audit.record(session, current_user['user_id'], 'invitation.create',
                         target=f'invitation:{row.id}',
                         detail=f"uses={row.max_uses}"
                                + (f", expires {expires_at.isoformat()}" if expires_at else ', no expiry')
                                + (f", note: {note}" if note else ''))

            return jsonify({
                'message': 'Invitation created. Copy the link now — it is not shown again.',
                'invitation': row.to_dict(),
                'code': code,
                'link': _link_for(code),
            }), 201
    except Exception as e:
        logger.error(f"Create invitation error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@invitations_bp.route('/<int:invitation_id>', methods=['DELETE'])
@token_required
def revoke_invitation(current_user, invitation_id):
    """Revoke an invitation. Players may only revoke their own."""
    try:
        with db.get_db() as session:
            row = session.query(Invitation).filter_by(id=invitation_id).first()
            if not row:
                return jsonify({'error': 'Invitation not found'}), 404
            if not _is_staff(current_user) and row.created_by != current_user['user_id']:
                return jsonify({'error': 'Access denied'}), 403
            if row.revoked_at is not None:
                return jsonify({'error': 'That invitation is already revoked'}), 409

            row.revoked_at = datetime.utcnow()
            audit.record(session, current_user['user_id'], 'invitation.revoke',
                         target=f'invitation:{invitation_id}')
            return jsonify({'message': 'Invitation revoked'}), 200
    except Exception as e:
        logger.error(f"Revoke invitation error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

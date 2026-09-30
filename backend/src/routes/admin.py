"""Admin panel routes.

User management is handled locally (backend owns the `users` table). Server and
task operations are proxied to the game-server API, which owns those tables.
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy import func, or_
from flask import Blueprint, request, jsonify, Response, stream_with_context
from src.database import db
from src.models.user import User
from src.models.character import Character
from src.models.claim_request import ClaimRequest
from src.models.reward import Reward
from src.models.box import Box
from src.models.event import Event
from src.models.event_box import EventBox
from src.models.box_loot_pool import BoxLootPool
from src.models.user_box import UserBox
from src.models.inventory_item import InventoryItem
from src.models.audit_log import AuditLog
from src.models.notification import Notification
from src.models.ban import Ban
from src.models.alert_channel import AlertChannel
from src.middleware.auth import moderator_required, admin_required
from src.utils.game_server import gs_request, gs_stream
from src.utils.redis_utils import apply_live_state
from src.utils import (loot, audit, settings, mailer, paging, notify, jobs, moderation,
                       alerting, channels)
from src.utils.actions import fetch_catalog, role_allows, validate_action
from src.utils.rewards import (validate_reward_payload, validate_usable_commands,
                               validate_item_count)

logger = logging.getLogger(__name__)
admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')

# Map control actions to the commands the orchestrator listens for.
SERVER_CONTROL_ACTIONS = {'start', 'stop', 'sleep', 'command'}


# ---------------------------------------------------------------------------
# User management (local)
# ---------------------------------------------------------------------------

@admin_bp.route('/users', methods=['GET'])
@moderator_required
def get_users(current_user):
    """Get all users (moderator/admin only)"""
    try:
        limit, offset = paging.params()
        role = request.args.get('role')

        with db.get_db() as session:
            query = session.query(User).order_by(User.id.asc())
            if role:
                query = query.filter_by(role=role)
            users, total = paging.page(query, limit, offset)
            loot_held = _loot_summary(session, [u.id for u in users])

            return jsonify({
                'users': [dict(u.to_dict(), **loot_held[u.id]) for u in users],
                'pagination': paging.meta(total, limit, offset)
            }), 200
    except Exception as e:
        logger.error(f"Get users error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# Loot an account still holds: boxes it has not opened, and rewards it has not
# sent. Expired rows are left out even before the sweep marks them, matching
# what the player's own pages offer.
_PENDING_ITEM_STATUSES = (InventoryItem.STATUS_HELD, InventoryItem.STATUS_FAILED)


def _not_expired(model, now):
    return or_(model.expires_at.is_(None), model.expires_at > now)


def _pending_boxes(session, user_ids, now):
    return (session.query(UserBox)
            .filter(UserBox.user_id.in_(user_ids),
                    UserBox.status == UserBox.STATUS_UNOPENED,
                    _not_expired(UserBox, now)))


def _pending_items(session, user_ids, now):
    return (session.query(InventoryItem)
            .filter(InventoryItem.user_id.in_(user_ids),
                    InventoryItem.status.in_(_PENDING_ITEM_STATUSES),
                    _not_expired(InventoryItem, now)))


def _loot_summary(session, user_ids):
    """``{user_id: {unopened_boxes, held_rewards}}``.

    Two grouped queries for the whole page rather than two per user.
    """
    out = {uid: {'unopened_boxes': 0, 'held_rewards': 0} for uid in user_ids}
    if not user_ids:
        return out
    now = datetime.utcnow()

    box_counts = (_pending_boxes(session, user_ids, now)
                  .with_entities(UserBox.user_id, func.count(UserBox.id))
                  .group_by(UserBox.user_id))
    for uid, n in box_counts:
        out[uid]['unopened_boxes'] = n

    item_counts = (_pending_items(session, user_ids, now)
                   .with_entities(InventoryItem.user_id, func.count(InventoryItem.id))
                   .group_by(InventoryItem.user_id))
    for uid, n in item_counts:
        out[uid]['held_rewards'] = n
    return out


@admin_bp.route('/users/<int:user_id>', methods=['GET'])
@admin_required
def get_user_detail(current_user, user_id):
    """One account with everything its manage page acts on (admin only).

    Characters, unopened boxes and undelivered rewards. The loot is listed row
    by row, since that is the level removal works at.
    """
    try:
        with db.get_db() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if not user:
                return jsonify({'error': 'User not found'}), 404
            now = datetime.utcnow()

            characters = (session.query(Character)
                          .filter_by(user_id=user_id)
                          .order_by(Character.id.asc())
                          .all())
            boxes = (_pending_boxes(session, [user_id], now)
                     .order_by(UserBox.granted_at.desc())
                     .all())
            items = (_pending_items(session, [user_id], now)
                     .order_by(InventoryItem.created_at.desc())
                     .all())
            boxes_by_id = {b.id: b for b in session.query(Box).all()}
            reward_ids = {i.reward_id for i in items}
            rewards_by_id = ({r.id: r for r in
                              session.query(Reward).filter(Reward.id.in_(reward_ids))}
                             if reward_ids else {})

            return jsonify({
                'user': dict(user.to_dict(), **_loot_summary(session, [user_id])[user_id]),
                'characters': [c.to_dict() for c in characters],
                'boxes': [b.to_dict(box=boxes_by_id.get(b.box_id)) for b in boxes],
                'inventory': [i.to_dict(reward=rewards_by_id.get(i.reward_id)) for i in items],
            }), 200
    except Exception as e:
        logger.error(f"Get user detail error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


def _selected_ids(data):
    """``(ids, error)`` from a removal body: a list of ids, or ``all: true``.

    ``None`` for ids means "all of them". Parsed before any session opens, for
    the same reason as :func:`_parse_ban_duration`.
    """
    if data.get('all') is True:
        return None, None
    ids = data.get('ids')
    if not isinstance(ids, list) or not ids:
        return None, 'Give ids to remove, or all: true'
    try:
        return {int(i) for i in ids}, None
    except (TypeError, ValueError):
        return None, 'ids must be whole numbers'


@admin_bp.route('/users/<int:user_id>/boxes/remove', methods=['POST'])
@admin_required
def remove_user_boxes(current_user, user_id):
    """Take unopened boxes away from an account (admin only).

    The rows are marked revoked, not deleted: each is also the guard that stops
    the same event granting the same period twice, so deleting it would hand the
    box straight back on the player's next claim - and take a day off their
    streak with it.
    """
    ids, error = _selected_ids(request.get_json(silent=True) or {})
    if error:
        return jsonify({'error': error}), 400
    try:
        with db.get_db() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if not user:
                return jsonify({'error': 'User not found'}), 404
            query = (session.query(UserBox)
                     .filter_by(user_id=user_id, status=UserBox.STATUS_UNOPENED))
            if ids is not None:
                query = query.filter(UserBox.id.in_(ids))
            # Locked for the same reason opening locks: a box opened while it
            # is being revoked must end up one or the other, not both.
            rows = query.with_for_update().all()
            for row in rows:
                row.status = UserBox.STATUS_REVOKED
            if rows:
                audit.record(session, current_user['user_id'], 'user.boxes_removed',
                             target=f'user:{user_id}',
                             detail=f"{len(rows)} unopened box(es) removed from {user.username}")
            return jsonify({'message': f'Removed {len(rows)} box(es) from {user.username}.',
                            'removed': len(rows)}), 200
    except Exception as e:
        logger.error(f"Remove user boxes error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/users/<int:user_id>/inventory/remove', methods=['POST'])
@admin_required
def remove_user_inventory(current_user, user_id):
    """Delete undelivered rewards from an account (admin only).

    Only held or failed ones: a reward mid-delivery has a task on the manager
    that may still land in game, and deleting its row would lose the record of
    it rather than stop it.
    """
    ids, error = _selected_ids(request.get_json(silent=True) or {})
    if error:
        return jsonify({'error': error}), 400
    try:
        with db.get_db() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if not user:
                return jsonify({'error': 'User not found'}), 404
            query = (session.query(InventoryItem)
                     .filter(InventoryItem.user_id == user_id,
                             InventoryItem.status.in_(_PENDING_ITEM_STATUSES)))
            if ids is not None:
                query = query.filter(InventoryItem.id.in_(ids))
            rows = query.with_for_update().all()
            for row in rows:
                session.delete(row)
            if rows:
                audit.record(session, current_user['user_id'], 'user.inventory_removed',
                             target=f'user:{user_id}',
                             detail=f"{len(rows)} undelivered reward(s) removed from {user.username}")
            return jsonify({'message': f'Removed {len(rows)} reward(s) from {user.username}.',
                            'removed': len(rows)}), 200
    except Exception as e:
        logger.error(f"Remove user inventory error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


def _parse_ban_duration(data):
    """``(expires_at, error)`` for an optional `duration_days`.

    Parsed before any session opens: `get_db` commits on normal exit, so an
    error returned after a mutation would persist that mutation.
    """
    if not data.get('duration_days'):
        return None, None
    try:
        days = int(data['duration_days'])
    except (TypeError, ValueError):
        return None, 'duration_days must be a whole number'
    if days < 1 or days > 3650:
        return None, 'duration_days must be between 1 and 3650'
    return datetime.utcnow() + timedelta(days=days), None


def _record_ban_change(session, user_id, actor_id, previous, new_role, data, expires_at):
    """Open or close the ban row that goes with a role change.

    The role carries the live state; the ban row carries why, by whom, for how
    long, and what to restore.
    """
    if new_role == User.ROLE_BANNED and previous != User.ROLE_BANNED:
        session.add(Ban(
            user_id=user_id,
            issued_by=actor_id,
            reason=(data.get('reason') or '').strip() or None,
            expires_at=expires_at,
            prior_role=previous,
        ))
    elif previous == User.ROLE_BANNED and new_role != User.ROLE_BANNED:
        # Close any ban still open, so the history reads correctly.
        (session.query(Ban)
         .filter_by(user_id=user_id)
         .filter(Ban.lifted_at.is_(None))
         .update({'lifted_at': datetime.utcnow(), 'lifted_by': actor_id},
                 synchronize_session=False))


def _ban_notice(data, previous, new_role):
    """``(kind, title, body)`` telling the account what just happened to it.

    A ban is the one role change the account cannot discover for itself, since
    it is refused everywhere from the next request onward.
    """
    if new_role == User.ROLE_BANNED:
        reason = (data.get('reason') or '').strip()
        days = data.get('duration_days')
        body = ('You can no longer sign in. '
                + (f'This lasts {days} day(s). ' if days else 'This is permanent. ')
                + (f'Reason: {reason}' if reason
                   else 'Contact the server staff if you think this is wrong.'))
        return Notification.KIND_MODERATION, 'Your account has been banned', body

    return (Notification.KIND_ACCOUNT,
            f'Your role is now {new_role}',
            f'Changed from {previous}.')


@admin_bp.route('/users/<int:user_id>', methods=['PUT'])
@admin_required
def update_user_role(current_user, user_id):
    """Change a user's role, and carry a ban into the game (admin only)."""
    data = request.get_json()

    if not data or 'role' not in data:
        return jsonify({'error': 'Role is required'}), 400
    new_role = data['role']
    if new_role not in User.ROLES:
        return jsonify({'error': 'Invalid role'}), 400

    ban_expires_at, error = _parse_ban_duration(data)
    if error:
        return jsonify({'error': error}), 400

    actor_id = current_user['user_id']
    try:
        with db.get_db() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if not user:
                return jsonify({'error': 'User not found'}), 404

            previous = user.role
            user.role = new_role
            _record_ban_change(session, user_id, actor_id, previous, new_role,
                               data, ban_expires_at)

            audit.record(session, actor_id, 'user.role_change',
                         target=f'user:{user_id}',
                         detail=f"{user.username}: {previous} -> {new_role}")

            # Gathered inside the transaction, acted on outside it: each
            # game-server call can take up to its timeout, and holding this row
            # open across several would block the account for that long.
            sync_targets = []
            if new_role != previous:
                kind, title, body = _ban_notice(data, previous, new_role)
                notify.send(session, user_id, kind, title, body=body)
                if new_role == User.ROLE_BANNED or previous == User.ROLE_BANNED:
                    sync_targets = moderation.targets(session, user_id)

            result = user.to_dict()
            username = user.username

        # --- outside the transaction: the site ban has already landed ---
        if new_role != previous and (new_role == User.ROLE_BANNED
                                     or previous == User.ROLE_BANNED):
            banned = new_role == User.ROLE_BANNED
            alerting.emit(
                'user.banned' if banned else 'user.unbanned',
                f"{username} was {'banned' if banned else 'unbanned'}",
                fields=[('Account', username),
                        ('Reason', (data.get('reason') or '').strip() or None),
                        ('Until', 'permanent' if banned and not ban_expires_at
                         else (ban_expires_at.strftime('%d %b %Y') if ban_expires_at else None))]
            )

        outcomes = []
        if sync_targets:
            outcomes = (moderation.apply_ban(sync_targets, reason=data.get('reason'))
                        if new_role == User.ROLE_BANNED
                        else moderation.lift_ban(sync_targets))
            audit.record_standalone(actor_id, 'user.ban_sync',
                                    target=f'user:{user_id}',
                                    detail='; '.join(outcomes))

        return jsonify({
            'message': 'User role updated successfully',
            'user': result,
            # So a moderator sees what actually applied in game rather than
            # assuming it all did.
            'in_game': outcomes
        }), 200
    except Exception as e:
        logger.error(f"Update user role error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/users/<int:user_id>/bans', methods=['GET'])
@moderator_required
def get_user_bans(current_user, user_id):
    """This account's ban history, newest first (moderator/admin only).

    The question worth answering is "has this happened before?", which is why
    lifted bans stay in the list rather than being deleted.
    """
    try:
        with db.get_db() as session:
            rows = (session.query(Ban)
                    .filter_by(user_id=user_id)
                    .order_by(Ban.created_at.desc())
                    .all())
            return jsonify({'bans': [r.to_dict() for r in rows]}), 200
    except Exception as e:
        logger.error(f"Get user bans error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
@admin_required
def admin_reset_password(current_user, user_id):
    """Mail a one-time reset link to a user (admin only).

    Issues a link rather than returning or setting a password: a password handed
    over out-of-band ends up in a chat log, and this way the admin never learns
    the user's credentials. It is the answer for someone whose address works but
    who cannot get through the self-service flow.
    """
    from src.models.auth_token import AuthToken

    try:
        with db.get_db() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if not user:
                return jsonify({'error': 'User not found'}), 404

            # Minted but not stored until the mail is away: a token nobody
            # received is a live credential sitting in the database for nothing.
            row, plaintext = AuthToken.issue(user.id, AuthToken.PURPOSE_RESET)
            if not mailer.send_password_reset(user.email, user.username, plaintext):
                return jsonify({'error': 'Could not send the reset email'}), 502

            session.add(row)
            audit.record(session, current_user['user_id'], 'password.admin_reset',
                         target=f'user:{user_id}',
                         detail=f"reset link issued for {user.username}")
            return jsonify({'message': f'A reset link has been sent to {user.username}.'}), 200
    except Exception as e:
        logger.error(f"Admin reset password error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/users/<int:user_id>/disable-2fa', methods=['POST'])
@admin_required
def admin_disable_2fa(current_user, user_id):
    """Clear a user's two-factor auth (admin only).

    With no recovery codes, a lost authenticator locks the owner out for good -
    the code is the only key, and it lives on a device that is now gone. This is
    the deliberate way back in: an admin turns the factor off so the user can
    sign in with their password and, if they want, set it up again. It removes a
    control, so it is audited and admin-only.
    """
    try:
        with db.get_db() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if not user:
                return jsonify({'error': 'User not found'}), 404
            if not user.totp_enabled and not user.totp_secret:
                return jsonify({'error': 'This account does not have two-factor auth set up'}), 400

            user.totp_enabled = False
            user.totp_secret = None
            audit.record(session, current_user['user_id'], '2fa.admin_disabled',
                         target=f'user:{user_id}',
                         detail=f"two-factor auth cleared for {user.username}")
            notify.send(session, user_id, Notification.KIND_ACCOUNT,
                        'Two-factor authentication was turned off',
                        body=('An administrator turned off two-factor '
                              'authentication on your account. If this was not '
                              'expected, contact the server staff and set it up '
                              'again from your profile.'))
            return jsonify({'message': f'Two-factor auth cleared for {user.username}.',
                            'user': user.to_dict()}), 200
    except Exception as e:
        logger.error(f"Admin disable 2FA error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# Server management (proxied to the game-server API)
# ---------------------------------------------------------------------------

@admin_bp.route('/servers', methods=['GET'])
@moderator_required
def get_servers(current_user):
    """Get all servers (moderator/admin only)"""
    params = {}
    if request.args.get('limit'):
        params['limit'] = request.args.get('limit')
    if request.args.get('offset'):
        params['offset'] = request.args.get('offset')

    payload, status = gs_request('GET', '/api/servers', params=params)
    if status != 200:
        return jsonify({'error': payload.get('error', 'Failed to fetch servers')}), status
    return jsonify({'servers': apply_live_state(payload.get('data', []))}), 200


@admin_bp.route('/servers/<int:server_id>', methods=['GET'])
@moderator_required
def get_server(current_user, server_id):
    """Get a single server (moderator/admin only)"""
    payload, status = gs_request('GET', f'/api/servers/{server_id}')
    if status != 200:
        return jsonify({'error': payload.get('error', 'Server not found')}), status
    # Same live-state overlay the list gets: the server's own page is where
    # start/stop is now driven from, so it needs the actual state, not the
    # configured default.
    server = apply_live_state([payload.get('data') or {}])[0]
    return jsonify({'server': server}), 200


@admin_bp.route('/servers', methods=['POST'])
@admin_required
def create_server(current_user):
    """Create new server (admin only)"""
    data = request.get_json()
    if not data or not data.get('name'):
        return jsonify({'error': 'Server name is required'}), 400

    payload, status = gs_request('POST', '/api/servers', json=data)
    if status not in (200, 201):
        return jsonify({'error': payload.get('error', 'Failed to create server')}), status

    server = payload.get('data') or {}
    audit.record_standalone(current_user['user_id'], 'server.create',
                            target=f"server:{server.get('id')}",
                            detail=f"created '{server.get('name') or data.get('name')}'")
    return jsonify({
        'message': 'Server created successfully',
        'server': payload.get('data')
    }), status


@admin_bp.route('/servers/<int:server_id>', methods=['PUT'])
@admin_required
def update_server(current_user, server_id):
    """Update server (admin only)"""
    data = request.get_json() or {}

    payload, status = gs_request('PUT', f'/api/servers/{server_id}', json=data)
    if status != 200:
        return jsonify({'error': payload.get('error', 'Failed to update server')}), status

    # Field names only - the payload may carry rcon_password, and a secret must
    # not be copied into a table built to be read by every moderator.
    audit.record_standalone(current_user['user_id'], 'server.update',
                            target=f'server:{server_id}',
                            detail=f"changed: {', '.join(sorted(data.keys())) or 'nothing'}")
    return jsonify({
        'message': 'Server updated successfully',
        'server': payload.get('data')
    }), 200


@admin_bp.route('/servers/<int:server_id>', methods=['DELETE'])
@admin_required
def delete_server(current_user, server_id):
    """Delete server (admin only)"""
    payload, status = gs_request('DELETE', f'/api/servers/{server_id}')
    if status != 200:
        return jsonify({'error': payload.get('error', 'Failed to delete server')}), status

    audit.record_standalone(current_user['user_id'], 'server.delete',
                            target=f'server:{server_id}')
    return jsonify({'message': 'Server deleted successfully'}), 200


@admin_bp.route('/servers/<int:server_id>/<string:action>', methods=['POST'])
@moderator_required
def control_server(current_user, server_id, action):
    """Send a lifecycle command to a server (moderator/admin only).

    Valid actions: start, stop, sleep, command. ``command`` expects a JSON body
    with a ``command`` string that is forwarded to the running server console.
    """
    if action not in SERVER_CONTROL_ACTIONS:
        return jsonify({'error': f'Invalid action: {action}'}), 400

    body = None
    if action == 'command':
        data = request.get_json(silent=True) or {}
        if not data.get('command'):
            return jsonify({'error': 'A command string is required'}), 400
        body = {'command': data['command']}

    payload, status = gs_request('POST', f'/api/servers/{server_id}/{action}', json=body)
    if status not in (200, 202):
        return jsonify({'error': payload.get('error', 'Failed to send command')}), status

    # RCON returns what the console printed; the stdin path returns nothing but
    # an acknowledgement. Pass through whichever happened so the panel can show
    # a result rather than implying one.
    result = payload.get('data') or {}

    # The command string is the record: "who ran that on the server" is
    # unanswerable without it. Lifecycle actions carry no detail of their own.
    audit.record_standalone(current_user['user_id'], f'server.{action}',
                            target=f'server:{server_id}',
                            detail=body['command'] if body else None)
    return jsonify({
        'message': payload.get('message', 'Command sent successfully'),
        'output': result.get('output'),
        'via': result.get('via', 'stdin')
    }), 200


@admin_bp.route('/servers/<int:server_id>/logs', methods=['GET'])
@moderator_required
def get_server_logs(current_user, server_id):
    """Tail a server's log (moderator/admin only)."""
    params = {'lines': request.args.get('lines', 200)}
    payload, status = gs_request('GET', f'/api/servers/{server_id}/logs', params=params)
    if status != 200:
        return jsonify({'error': payload.get('error', 'Could not read the log')}), status
    return jsonify(payload.get('data') or {}), 200


@admin_bp.route('/servers/<int:server_id>/backups', methods=['GET'])
@moderator_required
def get_server_backups(current_user, server_id):
    """World archives held for a server (moderator/admin only)."""
    payload, status = gs_request('GET', f'/api/servers/{server_id}/backups')
    if status != 200:
        return jsonify({'error': payload.get('error', 'Could not list backups')}), status
    return jsonify({'backups': payload.get('data') or []}), 200


@admin_bp.route('/servers/<int:server_id>/backups', methods=['POST'])
@admin_required
def create_server_backup(current_user, server_id):
    """Queue a world backup (admin only).

    Queued rather than run inline: archiving a world takes as long as it takes,
    and a request that waits for it would time out in the browser.
    """
    data = request.get_json(silent=True) or {}
    payload, status = gs_request('POST', '/api/tasks', json={
        'action': 'backup_world',
        'server_id': server_id,
        'note': data.get('note'),
    })
    if status not in (200, 201):
        return jsonify({'error': payload.get('error', 'Could not queue the backup')}), status

    audit.record_standalone(current_user['user_id'], 'server.backup',
                            target=f'server:{server_id}',
                            detail=data.get('note') or None)
    return jsonify({'message': 'Backup queued', 'task': payload.get('data')}), 202


@admin_bp.route('/servers/<int:server_id>/restore', methods=['POST'])
@admin_required
def restore_server_backup(current_user, server_id):
    """Queue a world restore (admin only). The server must be stopped."""
    data = request.get_json(silent=True) or {}
    backup = (data.get('backup') or '').strip()
    if not backup:
        return jsonify({'error': 'Which backup?'}), 400

    payload, status = gs_request('POST', '/api/tasks', json={
        'action': 'restore_world',
        'server_id': server_id,
        'backup': backup,
    })
    if status not in (200, 201):
        return jsonify({'error': payload.get('error', 'Could not queue the restore')}), status

    audit.record_standalone(current_user['user_id'], 'server.restore',
                            target=f'server:{server_id}',
                            detail=f'from {backup}')
    return jsonify({'message': 'Restore queued', 'task': payload.get('data')}), 202


@admin_bp.route('/servers/<int:server_id>/backups/upload', methods=['POST'])
@admin_required
def upload_server_backup(current_user, server_id):
    """Forward an operator-supplied archive to the game-server (admin only).

    Streamed straight through rather than buffered here: a world archive can be
    large, and the backend has no reason to hold it in memory on the way past.
    """
    upload = request.files.get('file')
    if not upload or not upload.filename:
        return jsonify({'error': 'No file uploaded'}), 400

    response, error = gs_stream(
        'POST', f'/api/servers/{server_id}/backups/upload',
        files={'file': (upload.filename, upload.stream, upload.mimetype
                        or 'application/gzip')},
    )
    if error:
        return jsonify(error[0]), error[1]

    try:
        payload = response.json()
    except ValueError:
        return jsonify({'error': 'Invalid response from game server'}), 502
    finally:
        response.close()

    if response.status_code not in (200, 201):
        return jsonify({'error': payload.get('error', 'Upload failed')}), response.status_code

    audit.record_standalone(current_user['user_id'], 'server.backup.upload',
                            target=f'server:{server_id}',
                            detail=(payload.get('data') or {}).get('name') or upload.filename)
    return jsonify(payload), 201


@admin_bp.route('/servers/<int:server_id>/backups/<archive_name>/download', methods=['GET'])
@admin_required
def download_server_backup(current_user, server_id, archive_name):
    """Stream a backup archive down to the operator (admin only)."""
    response, error = gs_stream(
        'GET', f'/api/servers/{server_id}/backups/{archive_name}/download')
    if error:
        return jsonify(error[0]), error[1]

    if response.status_code != 200:
        # The error body is small JSON; read it and pass it on rather than
        # streaming a 404 page back as if it were an archive.
        try:
            payload = response.json()
        except ValueError:
            payload = {'error': 'Could not download the backup'}
        finally:
            response.close()
        return jsonify(payload), response.status_code

    audit.record_standalone(current_user['user_id'], 'server.backup.download',
                            target=f'server:{server_id}', detail=archive_name)

    def generate():
        try:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if chunk:
                    yield chunk
        finally:
            response.close()

    headers = {
        'Content-Disposition': f'attachment; filename="{archive_name}"',
    }
    length = response.headers.get('Content-Length')
    if length:
        headers['Content-Length'] = length
    return Response(stream_with_context(generate()),
                    mimetype='application/gzip', headers=headers)


@admin_bp.route('/servers/<int:server_id>/backups/<archive_name>', methods=['DELETE'])
@admin_required
def delete_server_backup(current_user, server_id, archive_name):
    """Delete a backup archive (admin only)."""
    payload, status = gs_request(
        'DELETE', f'/api/servers/{server_id}/backups/{archive_name}')
    if status != 200:
        return jsonify({'error': payload.get('error', 'Could not delete the backup')}), status

    audit.record_standalone(current_user['user_id'], 'server.backup.delete',
                            target=f'server:{server_id}', detail=archive_name)
    return jsonify({'message': payload.get('message', 'Deleted')}), 200


@admin_bp.route('/servers/<int:server_id>/config', methods=['GET'])
@moderator_required
def get_server_config(current_user, server_id):
    """A server's editable settings (moderator/admin only)."""
    payload, status = gs_request('GET', f'/api/servers/{server_id}/config')
    if status != 200:
        return jsonify({'error': payload.get('error', 'Could not read the config')}), status
    return jsonify({'settings': payload.get('data') or []}), 200


@admin_bp.route('/servers/<int:server_id>/config', methods=['PUT'])
@admin_required
def update_server_config(current_user, server_id):
    """Change a server's settings (admin only).

    Values are never audited - two of the editable keys are passwords. The key
    names are, which is what an audit trail actually needs.
    """
    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({'error': 'Nothing to change'}), 400

    payload, status = gs_request('PUT', f'/api/servers/{server_id}/config', json=data)
    if status != 200:
        return jsonify({'error': payload.get('error', 'Could not write the config')}), status

    changed = (payload.get('data') or {}).get('changed') or []
    audit.record_standalone(current_user['user_id'], 'server.config',
                            target=f'server:{server_id}',
                            detail=f"changed: {', '.join(sorted(changed)) or 'nothing'}")
    return jsonify({
        'message': payload.get('message', 'Settings updated'),
        'changed': changed
    }), 200


@admin_bp.route('/servers/<int:server_id>/mods', methods=['GET'])
@moderator_required
def get_server_mods(current_user, server_id):
    """A server's mod configuration against what is downloaded."""
    payload, status = gs_request('GET', f'/api/servers/{server_id}/mods')
    if status != 200:
        return jsonify({'error': payload.get('error', 'Could not read the mod list')}), status
    return jsonify(payload.get('data') or {}), 200


@admin_bp.route('/servers/<int:server_id>/mods', methods=['PUT'])
@moderator_required
def update_server_mods(current_user, server_id):
    """Set which of the downloaded mods a server loads (moderator/admin).

    A moderator may turn mods on and off but may not *install* anything, so a
    non-admin's change is constrained to content already on disk. The split is
    deliberate: switching a mod off is how you fix a server at 3am, while
    installing one spends bandwidth, disk and several minutes of the task queue.
    """
    data = request.get_json(silent=True) or {}
    # Set here rather than trusted from the request: it is an authorisation
    # decision, and the browser does not get a say in it.
    data['downloaded_only'] = current_user.get('role') != 'admin'

    payload, status = gs_request('PUT', f'/api/servers/{server_id}/mods', json=data)
    if status != 200:
        return jsonify({'error': payload.get('error', 'Could not save the mod list')}), status

    audit.record_standalone(current_user['user_id'], 'server.mods',
                            target=f'server:{server_id}',
                            detail=f"{len(data.get('workshop_ids') or [])} item(s), "
                                   f"{len(data.get('mod_names') or [])} mod(s)")
    return jsonify({
        'message': payload.get('message', 'Mod list saved'),
        'mods': payload.get('data') or {}
    }), 200


@admin_bp.route('/servers/<int:server_id>/mods/update', methods=['POST'])
@admin_required
def download_server_mods(current_user, server_id):
    """Queue a Workshop download for this server's configured mods (admin only)."""
    payload, status = gs_request('POST', '/api/tasks', json={
        'action': 'update_mods',
        'server_id': server_id,
    })
    if status not in (200, 201):
        return jsonify({'error': payload.get('error', 'Could not queue the download')}), status

    audit.record_standalone(current_user['user_id'], 'server.mods_update',
                            target=f'server:{server_id}')
    return jsonify({'message': 'Download queued', 'task': payload.get('data')}), 202


@admin_bp.route('/servers/<int:server_id>/config/raw', methods=['GET'])
@admin_required
def get_server_config_raw(current_user, server_id):
    """Every key in a server's INI, including disabled ones (admin only).

    Admin rather than moderator: this exposes undeclared keys, which is the
    screen where somebody can quietly break a server.
    """
    payload, status = gs_request('GET', f'/api/servers/{server_id}/config/raw')
    if status != 200:
        return jsonify({'error': payload.get('error', 'Could not read the config')}), status
    return jsonify(payload.get('data') or {}), 200


@admin_bp.route('/servers/<int:server_id>/config/raw', methods=['PUT'])
@admin_required
def update_server_config_raw(current_user, server_id):
    """Apply raw INI edits (admin only). Refused unless the server is off."""
    data = request.get_json(silent=True) or {}
    changes = data.get('changes') or {}
    if not changes:
        return jsonify({'error': 'Nothing to change'}), 400

    payload, status = gs_request('PUT', f'/api/servers/{server_id}/config/raw', json=data)
    if status != 200:
        return jsonify({'error': payload.get('error', 'Could not write the config')}), status

    result = payload.get('data') or {}
    # Key names only. Two of these keys are passwords, and an audit log every
    # moderator can read is the wrong place for them.
    audit.record_standalone(current_user['user_id'], 'server.config_raw',
                            target=f'server:{server_id}',
                            detail=f"changed: {', '.join(sorted(result.get('changed') or [])) or 'nothing'}")
    return jsonify({
        'message': payload.get('message', 'Config updated'),
        'changed': result.get('changed') or [],
        'version': result.get('version')
    }), 200


@admin_bp.route('/servers/<int:server_id>/config/template/export', methods=['GET'])
@admin_required
def export_server_config_template(current_user, server_id):
    """Build a portable config template from a server (admin only, proxied).

    The game-server filters out ports, credentials and per-server identity, so
    the returned JSON is safe to publish to the community repo and import onto
    another server.
    """
    params = {'name': request.args.get('name', ''),
              'description': request.args.get('description', '')}
    payload, status = gs_request('GET', f'/api/servers/{server_id}/config/template',
                                 params=params)
    if status != 200:
        return jsonify({'error': payload.get('error', 'Could not export the config')}), status
    return jsonify(payload.get('data') or {}), 200


@admin_bp.route('/servers/<int:server_id>/config/template/import', methods=['POST'])
@admin_required
def import_server_config_template(current_user, server_id):
    """Apply a combined template to a server (admin only, proxied).

    The template may come from the community list or a local file; either way it
    arrives as ``{settings?, sandbox?, version?, sandbox_version?}`` - at least
    one of the two halves must be present. The game-server re-filters each half
    against its own blacklist before a byte is written. Refused unless off.
    """
    data = request.get_json(silent=True) or {}
    settings = data.get('settings')
    sandbox = data.get('sandbox')
    has_settings = isinstance(settings, dict) and settings
    has_sandbox = isinstance(sandbox, dict) and sandbox
    if not has_settings and not has_sandbox:
        return jsonify({'error': 'The template has no settings or sandbox values'}), 400

    payload, status = gs_request(
        'POST', f'/api/servers/{server_id}/config/template',
        json={
            'settings': settings if has_settings else None,
            'sandbox': sandbox if has_sandbox else None,
            'version': data.get('version'),
            'sandbox_version': data.get('sandbox_version'),
        }
    )
    if status != 200:
        return jsonify({'error': payload.get('error', 'Could not import the template')}), status

    result = payload.get('data') or {}
    ini = result.get('settings') or {}
    sb = result.get('sandbox') or {}
    changed = (ini.get('changed') or []) + (sb.get('changed') or [])
    skipped = (ini.get('skipped') or []) + (sb.get('skipped') or [])
    audit.record_standalone(current_user['user_id'], 'server.config_template',
                            target=f'server:{server_id}',
                            detail=f"applied: {', '.join(sorted(changed)) or 'nothing'}"
                                   + (f"; skipped: {', '.join(sorted(skipped))}" if skipped else ''))
    return jsonify({
        'message': payload.get('message', 'Template applied'),
        'changed': changed,
        'skipped': skipped,
    }), 200


# ---------------------------------------------------------------------------
# SandboxVars: the gameplay-difficulty half of a server's config (a Lua file,
# handled separately from the .ini). Water/power shutoff, loot abundance, zombie
# population, stats decay. Admin only, like the raw config editor.
# ---------------------------------------------------------------------------

@admin_bp.route('/servers/<int:server_id>/config/sandbox', methods=['GET'])
@admin_required
def get_server_sandbox(current_user, server_id):
    """The top-level SandboxVars for a server (admin only, proxied)."""
    payload, status = gs_request('GET', f'/api/servers/{server_id}/config/sandbox')
    if status != 200:
        return jsonify({'error': payload.get('error', 'Could not read the sandbox')}), status
    return jsonify(payload.get('data') or {}), 200


@admin_bp.route('/servers/<int:server_id>/config/sandbox', methods=['PUT'])
@admin_required
def update_server_sandbox(current_user, server_id):
    """Apply SandboxVars edits (admin only). Refused unless the server is off."""
    data = request.get_json(silent=True) or {}
    changes = data.get('changes') or {}
    if not changes:
        return jsonify({'error': 'Nothing to change'}), 400

    payload, status = gs_request('PUT', f'/api/servers/{server_id}/config/sandbox', json=data)
    if status != 200:
        return jsonify({'error': payload.get('error', 'Could not write the sandbox')}), status

    result = payload.get('data') or {}
    audit.record_standalone(current_user['user_id'], 'server.sandbox',
                            target=f'server:{server_id}',
                            detail=f"changed: {', '.join(sorted(result.get('changed') or [])) or 'nothing'}")
    return jsonify({
        'message': payload.get('message', 'Sandbox updated'),
        'changed': result.get('changed') or [],
        'version': result.get('version')
    }), 200


# ---------------------------------------------------------------------------
# Claim request review (account ↔ in-game character linking)
# ---------------------------------------------------------------------------

@admin_bp.route('/claims', methods=['GET'])
@moderator_required
def get_claims(current_user):
    """List claim requests (moderator/admin only)"""
    try:
        limit, offset = paging.params()
        status = request.args.get('status')
        with db.get_db() as session:
            query = session.query(ClaimRequest)
            if status:
                query = query.filter_by(status=status)
            query = query.order_by(ClaimRequest.created_at.desc())
            claims, total = paging.page(query, limit, offset)
            return jsonify({
                'claims': [c.to_dict() for c in claims],
                'pagination': paging.meta(total, limit, offset)
            }), 200
    except Exception as e:
        logger.error(f"Get claims error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/claims/<int:claim_id>/revoke', methods=['POST'])
@moderator_required
def revoke_claim(current_user, claim_id):
    """Revoke a character link, releasing the in-game identity (moderator/admin).

    Claims are approved automatically on the online check, so this - not an
    approval queue - is the staff lever. It does exactly what the player's own
    unlink does, with a reason attached so they can see why.
    """
    data = request.get_json(silent=True) or {}
    reason = (data.get('reason') or '').strip()
    if not reason:
        return jsonify({'error': 'A reason is required'}), 400

    try:
        with db.get_db() as session:
            claim = session.query(ClaimRequest).filter_by(id=claim_id).first()
            if not claim:
                return jsonify({'error': 'Claim not found'}), 404
            if claim.status == ClaimRequest.STATUS_REVOKED:
                return jsonify({'error': 'That link is already revoked'}), 409

            identity = f"{claim.in_game_username}@server{claim.server_id}"

            # Drop the character, which is what frees the in-game name.
            if claim.character_id:
                character = session.query(Character).filter_by(id=claim.character_id).first()
                if character:
                    session.delete(character)

            claim.status = ClaimRequest.STATUS_REVOKED
            claim.character_id = None
            claim.reason = reason
            claim.reviewed_by = current_user['user_id']
            claim.reviewed_at = datetime.utcnow()

            audit.record(session, current_user['user_id'], 'claim.revoke',
                         target=f'claim:{claim_id}',
                         detail=f"released {identity} from user {claim.user_id}: {reason}")
            notify.send(session, claim.user_id, Notification.KIND_MODERATION,
                        f'{claim.in_game_username} was unlinked from your account',
                        body=reason,
                        link='/characters')

            alerting.emit('character.revoked',
                          f'{claim.in_game_username} was unlinked by staff',
                          description=reason,
                          server_id=claim.server_id,
                          fields=[('Character', claim.in_game_username),
                                  ('Account', f'#{claim.user_id}')])

            return jsonify({'message': 'Link revoked', 'claim': claim.to_dict()}), 200
    except Exception as e:
        logger.error(f"Revoke claim error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# Boxes (a named box with a draw count) and their loot pools
# ---------------------------------------------------------------------------

def _box_health(box, entries, rewards_by_id):
    """Pool health for one box, so an empty pool is surfaced to an admin rather
    than discovered by a player who cannot open a box."""
    mine = [e for e in entries if e.box_id == box.id]
    live = [e for e in mine
            if (rewards_by_id.get(e.reward_id) is not None
                and rewards_by_id[e.reward_id].active
                and (e.weight or 0) > 0)]
    return {
        'box_id': box.id,
        'name': box.name,
        'draws': box.draws,
        'entries': len(mine),
        'droppable': len(live),
        # A box drawing more than its pool holds still works (it repeats), but
        # it is thin and worth flagging.
        'thin': 0 < len(live) < box.draws,
        'empty': len(live) == 0,
    }


@admin_bp.route('/boxes', methods=['GET'])
@moderator_required
def get_boxes(current_user):
    """Every box with its loot pool and pool health."""
    try:
        with db.get_db() as session:
            boxes = session.query(Box).order_by(Box.name).all()
            entries = session.query(BoxLootPool).all()
            rewards_by_id = {r.id: r for r in session.query(Reward).all()}

            pools_by_box = {}
            for e in entries:
                row = e.to_dict()
                reward = rewards_by_id.get(e.reward_id)
                row['reward'] = reward.to_dict() if reward else None
                pools_by_box.setdefault(e.box_id, []).append(row)

            # Which events each box takes part in, for the "Events" column.
            events_by_box = {}
            event_rows = (session.query(EventBox, Event)
                          .join(Event, EventBox.event_id == Event.id)
                          .order_by(Event.system.desc(), Event.type, Event.id).all())
            for link, event in event_rows:
                events_by_box.setdefault(link.box_id, []).append(
                    {'id': event.id, 'name': event.name, 'type': event.type})

            result = []
            for box in boxes:
                result.append({
                    **box.to_dict(),
                    'pool': pools_by_box.get(box.id, []),
                    'events': events_by_box.get(box.id, []),
                    'health': _box_health(box, entries, rewards_by_id),
                })
            return jsonify({'boxes': result}), 200
    except Exception as ex:
        logger.error(f"Get boxes error: {ex}")
        return jsonify({'error': 'Internal server error'}), 500


def _validate_box_fields(data, require_name=True):
    """Return ``(fields, error)`` for a box create/update payload."""
    fields = {}
    if 'name' in data or require_name:
        name = (data.get('name') or '').strip()
        if not name:
            return None, 'name is required'
        if len(name) > 64:
            return None, 'name must be 64 characters or fewer'
        fields['name'] = name
    if 'description' in data:
        fields['description'] = (data.get('description') or '').strip() or None
    if 'draws' in data or require_name:
        try:
            draws = int(data.get('draws', 1))
        except (TypeError, ValueError):
            return None, 'draws must be a whole number'
        if draws < 0 or draws > 20:
            return None, 'draws must be between 0 and 20'
        fields['draws'] = draws
    return fields, None


@admin_bp.route('/boxes', methods=['POST'])
@admin_required
def create_box(current_user):
    """Create a box (admin only)."""
    data = request.get_json(silent=True) or {}
    fields, error = _validate_box_fields(data, require_name=True)
    if error:
        return jsonify({'error': error}), 400
    try:
        with db.get_db() as session:
            if session.query(Box).filter(Box.name == fields['name']).first():
                return jsonify({'error': 'A box with that name already exists'}), 409
            box = Box(**fields)
            session.add(box)
            session.flush()
            audit.record(session, current_user['user_id'], 'box.create',
                         target=f'box:{box.id}', detail=f"'{box.name}'")
            return jsonify({'message': 'Box created', 'box': box.to_dict()}), 201
    except Exception as ex:
        logger.error(f"Create box error: {ex}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/boxes/<int:box_id>', methods=['PUT'])
@admin_required
def update_box(current_user, box_id):
    """Edit a box's name, description or draw count (admin only)."""
    data = request.get_json(silent=True) or {}
    fields, error = _validate_box_fields(data, require_name=False)
    if error:
        return jsonify({'error': error}), 400
    try:
        with db.get_db() as session:
            box = session.get(Box, box_id)
            if not box:
                return jsonify({'error': 'Box not found'}), 404
            if 'name' in fields:
                clash = (session.query(Box)
                         .filter(Box.name == fields['name'], Box.id != box_id).first())
                if clash:
                    return jsonify({'error': 'A box with that name already exists'}), 409
            for key, value in fields.items():
                setattr(box, key, value)
            audit.record(session, current_user['user_id'], 'box.update',
                         target=f'box:{box_id}', detail=', '.join(fields) or 'nothing')
            result = box.to_dict()
            return jsonify({'message': 'Box updated', 'box': result}), 200
    except Exception as ex:
        logger.error(f"Update box error: {ex}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/boxes/<int:box_id>', methods=['DELETE'])
@admin_required
def delete_box(current_user, box_id):
    """Delete a box (admin only).

    Any event line-ups the box is part of are removed with it, so deleting a box
    also takes it out of every event it was dropping from. It is still refused
    once the box has been granted to a player: removing it would orphan a grant
    somebody is holding. Its loot pool is owned by the box and goes with it.
    """
    try:
        with db.get_db() as session:
            box = session.get(Box, box_id)
            if not box:
                return jsonify({'error': 'Box not found'}), 404

            granted = session.query(UserBox).filter_by(box_id=box_id).count()
            if granted:
                return jsonify({'error': 'This box has already been granted to players, so '
                                         'it cannot be deleted. Remove it from its events to '
                                         'stop it dropping.'}), 409

            # Take it out of every event first: the box is going away, so its
            # event line-up entries go with it rather than blocking the delete.
            removed_from = (session.query(EventBox).filter_by(box_id=box_id).delete())

            name = box.name
            session.delete(box)   # box_loot_pools cascade with it
            detail = f"'{name}'"
            if removed_from:
                detail += f" (removed from {removed_from} event{'s' if removed_from != 1 else ''})"
            audit.record(session, current_user['user_id'], 'box.delete',
                         target=f'box:{box_id}', detail=detail)
            return jsonify({'message': 'Box deleted'}), 200
    except Exception as ex:
        logger.error(f"Delete box error: {ex}")
        return jsonify({'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# Loot box pool configuration (which rewards each box can contain)
# ---------------------------------------------------------------------------

@admin_bp.route('/box-pools', methods=['POST'])
@admin_required
def add_box_pool(current_user):
    """Add a reward to a box's loot pool (admin only)."""
    data = request.get_json() or {}
    box_id = data.get('box_id')
    reward_id = data.get('reward_id')
    if not box_id:
        return jsonify({'error': 'box_id is required'}), 400
    if not reward_id:
        return jsonify({'error': 'reward_id is required'}), 400

    weight = data.get('weight', 1)
    try:
        weight = float(weight)
    except (TypeError, ValueError):
        return jsonify({'error': 'weight must be a number'}), 400
    if weight < 0 or weight > 1000:
        return jsonify({'error': 'weight must be between 0 and 1000'}), 400

    count = data.get('count', 1)
    count_error = validate_item_count(count)
    if count_error:
        return jsonify({'error': count_error}), 400
    try:
        with db.get_db() as session:
            box = session.get(Box, box_id)
            if not box:
                return jsonify({'error': 'Box not found'}), 404
            reward = session.query(Reward).filter_by(id=reward_id).first()
            if not reward:
                return jsonify({'error': 'Reward not found'}), 404
            existing = session.query(BoxLootPool).filter_by(box_id=box_id, reward_id=reward_id).first()
            if existing:
                return jsonify({'error': 'Reward already in this pool'}), 409
            entry = BoxLootPool(box_id=box_id, reward_id=reward_id, weight=weight, count=count)
            session.add(entry)
            session.flush()
            audit.record(session, current_user['user_id'], 'box_pool.add',
                         target=f'pool:{entry.id}',
                         detail=f"'{reward.name}' added to the '{box.name}' pool "
                                f"at weight {weight}, count {count}")
            return jsonify({'message': 'Added to pool', 'pool': entry.to_dict()}), 201
    except Exception as ex:
        logger.error(f"Add box pool error: {ex}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/box-pools/<int:entry_id>', methods=['DELETE'])
@admin_required
def delete_box_pool(current_user, entry_id):
    """Remove a reward from a box loot pool (admin only)."""
    try:
        with db.get_db() as session:
            entry = session.query(BoxLootPool).filter_by(id=entry_id).first()
            if not entry:
                return jsonify({'error': 'Pool entry not found'}), 404
            # Read the details before the row goes away.
            box = session.get(Box, entry.box_id)
            reward = session.query(Reward).filter_by(id=entry.reward_id).first()
            session.delete(entry)
            audit.record(session, current_user['user_id'], 'box_pool.remove',
                         target=f'pool:{entry_id}',
                         detail=(f"'{reward.name if reward else entry_id}' removed from the "
                                 f"'{box.name if box else entry.box_id}' pool"))
            return jsonify({'message': 'Removed from pool'}), 200
    except Exception as ex:
        logger.error(f"Delete box pool error: {ex}")
        return jsonify({'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# Community box configs (import a loot pool from GitHub or a local file, export
# the current one)
#
# A box config is a portable description of one size's loot pool: a list of
# rewards, each carrying its full definition plus a drop weight, and the box's
# own draw count. Importing it creates any reward the catalog is missing
# (matched by name + kind, never mutating an existing one) and sets this box's
# pool weights; `draws` is applied only when the config creates the box, since
# silently rewriting an existing box's draw count is not what "import a pool"
# should mean. The community
# list is fetched by the game-server - the backend has no egress - and applied
# here; a local-file import skips the fetch and posts the same JSON directly.
# ---------------------------------------------------------------------------

# The whole box config crosses a trust boundary (it is authored elsewhere), so
# it is bounded like any other external input before a single row is written.
MAX_CONFIG_REWARDS = 100
MAX_POOL_WEIGHT = 1000
REWARD_BOXES_PROXY_TIMEOUT = 20


@admin_bp.route('/reward-boxes', methods=['GET'])
@moderator_required
def list_reward_boxes(current_user):
    """The community loot-box config index (proxied to the game-server).

    Reference data fetched from GitHub by the manager, the only service with
    egress. ``stale`` reports a failed refresh without discarding a usable list.
    """
    params = {'refresh': '1'} if request.args.get('refresh') in ('1', 'true', 'yes') else None
    payload, status = gs_request('GET', '/api/reward-boxes', params=params,
                                 timeout=REWARD_BOXES_PROXY_TIMEOUT)
    if status != 200:
        return jsonify({'error': payload.get('error', 'The community box list is unavailable')}), status
    data = payload.get('data') or {}
    return jsonify({'boxes': data.get('boxes', []), 'source': data.get('source'),
                    'stale': payload.get('stale')}), 200


@admin_bp.route('/reward-boxes/<string:box_id>', methods=['GET'])
@moderator_required
def get_reward_box(current_user, box_id):
    """One community box config, for preview before import (proxied)."""
    payload, status = gs_request('GET', f'/api/reward-boxes/{box_id}',
                                 timeout=REWARD_BOXES_PROXY_TIMEOUT)
    if status != 200:
        return jsonify({'error': payload.get('error', 'The box config is unavailable')}), status
    return jsonify({'config': payload.get('data') or {}}), 200


@admin_bp.route('/server-templates', methods=['GET'])
@admin_required
def list_server_templates(current_user):
    """The community server-config template index (proxied to the game-server).

    Admin, like the config editor these templates apply to: the screen where
    somebody can quietly break a server is admin-only, and so is this. ``stale``
    reports a failed refresh without discarding a usable list.
    """
    params = {'refresh': '1'} if request.args.get('refresh') in ('1', 'true', 'yes') else None
    payload, status = gs_request('GET', '/api/server-templates', params=params,
                                 timeout=REWARD_BOXES_PROXY_TIMEOUT)
    if status != 200:
        return jsonify({'error': payload.get('error', 'The template list is unavailable')}), status
    data = payload.get('data') or {}
    return jsonify({'templates': data.get('templates', []), 'source': data.get('source'),
                    'stale': payload.get('stale')}), 200


@admin_bp.route('/server-templates/<string:template_id>', methods=['GET'])
@admin_required
def get_server_template(current_user, template_id):
    """One community server-config template, for preview before import (proxied)."""
    payload, status = gs_request('GET', f'/api/server-templates/{template_id}',
                                 timeout=REWARD_BOXES_PROXY_TIMEOUT)
    if status != 200:
        return jsonify({'error': payload.get('error', 'The template is unavailable')}), status
    return jsonify({'template': payload.get('data') or {}}), 200


def _prepare_config_reward(entry, index):
    """Validate one config reward. Returns ``(payload, weight, count, error, status)``.

    Applies the exact rules a hand-authored reward faces, so an external config
    can never introduce a reward the panel itself would have rejected. ``count``
    is the item drop quantity, which belongs to the box's pool entry rather than
    the reward, so it is returned separately from the reward ``payload``.
    """
    if not isinstance(entry, dict):
        return None, None, None, f'reward {index} is malformed', 400

    kind = entry.get('kind')
    name = (entry.get('name') or '').strip()
    payload = {
        'kind': kind,
        'name': name,
        'description': (entry.get('description') or '').strip(),
        'icon': (entry.get('icon') or '').strip(),
    }
    if kind == Reward.KIND_ITEM:
        payload['in_game_id'] = (entry.get('in_game_id') or '').strip()
    elif kind == Reward.KIND_USABLE:
        payload['commands'] = entry.get('commands')

    label = name or f'#{index}'
    error = validate_reward_payload(payload)
    if error:
        return None, None, None, f'reward "{label}": {error}', 400
    error, status = validate_usable_commands(payload)
    if error:
        return None, None, None, f'reward "{label}": {error}', status

    # Quantity is only meaningful for items; usables always run once.
    count = 1
    if kind == Reward.KIND_ITEM:
        count = entry.get('count', 1)
        count_error = validate_item_count(count)
        if count_error:
            return None, None, None, f'reward "{label}": {count_error}', 400

    weight = entry.get('weight', 1)
    try:
        weight = float(weight)
    except (TypeError, ValueError):
        return None, None, None, f'reward "{label}": weight must be a number', 400
    if weight < 0 or weight > MAX_POOL_WEIGHT:
        return None, None, None, f'reward "{label}": weight must be between 0 and {MAX_POOL_WEIGHT}', 400

    return payload, weight, count, None, 200


@admin_bp.route('/reward-boxes/import', methods=['POST'])
@admin_required
def import_reward_box(current_user):
    """Apply a box config to a size's loot pool (admin only).

    The config may come from the community list or a local file; either way it
    arrives here as ``{box_id, config, replace?}`` and is fully re-validated. With
    ``replace`` the pool is made to match the config exactly (entries absent from
    it are removed); otherwise the import merges - it adds and reweights without
    dropping rewards the config does not mention.
    """
    data = request.get_json(silent=True) or {}
    box_id = data.get('box_id')
    config = data.get('config')
    replace = bool(data.get('replace'))

    if not box_id:
        return jsonify({'error': 'box_id is required'}), 400
    if not isinstance(config, dict):
        return jsonify({'error': 'config is required'}), 400
    rewards_in = config.get('rewards')
    if not isinstance(rewards_in, list) or not rewards_in:
        return jsonify({'error': 'The config has no rewards'}), 400
    if len(rewards_in) > MAX_CONFIG_REWARDS:
        return jsonify({'error': f'A config may hold at most {MAX_CONFIG_REWARDS} rewards'}), 400

    # Validate everything before writing anything, so a bad entry halfway down
    # cannot leave a half-imported pool behind.
    prepared = []
    # Rewards are matched to the catalog by (name, kind), so two entries sharing
    # one would resolve to the same reward and then to the same pool row - which
    # trips the (box_id, reward_id) unique key at commit and surfaces as an
    # opaque 500. Caught here instead, where it can say which name is doubled.
    seen_keys = set()
    for index, entry in enumerate(rewards_in, start=1):
        payload, weight, count, error, status = _prepare_config_reward(entry, index)
        if error:
            return jsonify({'error': error}), status
        key = (payload['name'].lower(), payload['kind'])
        if key in seen_keys:
            return jsonify({'error': f"the config lists '{payload['name']}' "
                                     f"({payload['kind']}) more than once"}), 400
        seen_keys.add(key)
        prepared.append((payload, weight, count))

    try:
        summary = {'created': 0, 'reused': 0, 'added': 0, 'reweighted': 0, 'removed': 0}
        with db.get_db() as session:
            box = session.get(Box, box_id)
            if not box:
                return jsonify({'error': 'Box not found'}), 404
            # Match on name + kind: reusing an item reward for a usable of the
            # same name would put the wrong thing in the pool.
            existing = {}
            for r in session.query(Reward).all():
                existing.setdefault(((r.name or '').strip().lower(), r.kind), r)

            config_reward_ids = set()
            pool_targets = []
            for payload, weight, count in prepared:
                is_item = payload['kind'] == Reward.KIND_ITEM
                key = (payload['name'].lower(), payload['kind'])
                reward = existing.get(key)
                if reward is None:
                    reward = Reward(
                        kind=payload['kind'],
                        name=payload['name'],
                        description=payload.get('description', ''),
                        icon=payload.get('icon', ''),
                        in_game_id=payload.get('in_game_id') if is_item else None,
                        commands=payload.get('commands') if not is_item else None,
                        active=True,
                    )
                    session.add(reward)
                    session.flush()
                    existing[key] = reward
                    summary['created'] += 1
                else:
                    summary['reused'] += 1
                pool_targets.append((reward.id, weight, count))
                config_reward_ids.add(reward.id)

            pool_by_reward = {e.reward_id: e for e in
                              session.query(BoxLootPool).filter_by(box_id=box_id).all()}
            for reward_id, weight, count in pool_targets:
                entry = pool_by_reward.get(reward_id)
                if entry is None:
                    session.add(BoxLootPool(box_id=box_id, reward_id=reward_id,
                                            weight=weight, count=count))
                    summary['added'] += 1
                elif entry.weight != weight or entry.count != count:
                    entry.weight = weight
                    entry.count = count
                    summary['reweighted'] += 1

            if replace:
                for reward_id, entry in pool_by_reward.items():
                    if reward_id not in config_reward_ids:
                        session.delete(entry)
                        summary['removed'] += 1

            audit.record(session, current_user['user_id'], 'reward_box.import',
                         target=f'box:{box_id}',
                         detail=(f"'{(config.get('name') or 'config')}' -> '{box.name}': "
                                 f"{summary['created']} created, {summary['added']} added, "
                                 f"{summary['reweighted']} reweighted, {summary['removed']} removed"))
        return jsonify({'message': 'Box config imported', 'summary': summary}), 200
    except Exception as ex:
        logger.error(f"Import reward box error: {ex}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/reward-boxes/export', methods=['GET'])
@admin_required
def export_reward_box(current_user):
    """Build a portable config from a size's current loot pool (admin only).

    Returns the same ``box-config/v1`` shape the importer accepts, so a box can
    be exported here, committed to the community repo, and imported elsewhere.
    """
    box_id = request.args.get('box_id')
    name = (request.args.get('name') or '').strip()
    description = (request.args.get('description') or '').strip()
    if not box_id:
        return jsonify({'error': 'box_id is required'}), 400

    try:
        with db.get_db() as session:
            box = session.get(Box, int(box_id)) if str(box_id).isdigit() else None
            if not box:
                return jsonify({'error': 'Box not found'}), 404
            entries = session.query(BoxLootPool).filter_by(box_id=box.id).all()
            rewards_by_id = {r.id: r for r in session.query(Reward).all()}
            rewards_out = []
            for e in entries:
                reward = rewards_by_id.get(e.reward_id)
                if not reward:
                    continue
                is_item = reward.kind == Reward.KIND_ITEM
                out = {
                    'kind': reward.kind,
                    'name': reward.name,
                    'description': reward.description or '',
                    'icon': reward.icon or '',
                    'weight': e.weight,
                }
                if is_item:
                    out['in_game_id'] = reward.in_game_id
                    out['count'] = e.count or 1
                else:
                    out['commands'] = reward.commands or ''
                rewards_out.append(out)

        return jsonify({
            'schema': 'safezone.box-config/v1',
            'name': name or box.name,
            'description': description,
            # Carried so a config describes the whole box, not just its pool: a
            # three-draw box that round-tripped as a one-draw box was a silent
            # downgrade nobody would notice until players opened it. Only used
            # when the config creates a box; importing into an existing box
            # leaves that box's own draw count alone.
            'draws': box.draws,
            'rewards': rewards_out,
        }), 200
    except Exception as ex:
        logger.error(f"Export reward box error: {ex}")
        return jsonify({'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# Console action catalog
# ---------------------------------------------------------------------------

@admin_bp.route('/actions', methods=['GET'])
@moderator_required
def list_actions(current_user):
    """The console actions this staff member may run.

    Actions above the caller's role are filtered out, so a moderator never sees
    server operations they cannot run. ``?droppable=1`` narrows the list to
    actions that may back a player reward.
    """
    droppable_only = request.args.get('droppable') in ('1', 'true', 'yes')
    resp, status = fetch_catalog(droppable_only=droppable_only)
    if status != 200:
        return jsonify({'error': resp.get('error', 'Failed to load actions')}), status

    allowed = [a for a in resp.get('data', [])
               if role_allows(current_user.get('role'), a.get('min_role'))]
    return jsonify({'actions': allowed, 'categories': resp.get('categories', [])}), 200


# ---------------------------------------------------------------------------
# Reward delivery (admin direct-give)
# ---------------------------------------------------------------------------

@admin_bp.route('/give', methods=['POST'])
@moderator_required
def give_reward(current_user):
    """Run an item/action for an in-game character (moderator/admin only).

    Creates a give_reward delivery task on the game-server, which builds the
    console command safely and refuses player-targeted actions when the target
    is offline. Catalog actions are validated here first so a bad parameter is
    reported to the operator instead of failing silently inside a task.
    """
    data = request.get_json() or {}
    server_id = data.get('server_id')
    username = (data.get('in_game_username') or '').strip()
    kind = data.get('kind', 'item')

    if not server_id:
        return jsonify({'error': 'server_id is required'}), 400
    try:
        server_id = int(server_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid server_id'}), 400

    payload = {'action': 'give_reward', 'server_id': server_id, 'username': username, 'kind': kind}
    if kind == 'usable':
        if data.get('action_id'):
            action, command, error, status = validate_action(
                data['action_id'], data.get('action_params'), username=username or None
            )
            if error:
                return jsonify({'error': error}), status
            if not role_allows(current_user.get('role'), action.get('min_role')):
                return jsonify({'error': 'Your role cannot run this action'}), 403
            if action.get('targets_player') and not username:
                return jsonify({'error': 'in_game_username is required for this action'}), 400
            payload['action_id'] = data['action_id']
            payload['action_params'] = data.get('action_params') or {}
            payload['scope'] = 'staff'   # unlocks moderation/server actions
            detail_target = command
        else:
            return jsonify({'error': 'action_id is required for usables'}), 400
    else:
        if not username:
            return jsonify({'error': 'in_game_username is required'}), 400
        if not data.get('in_game_id'):
            return jsonify({'error': 'in_game_id is required for items'}), 400
        payload['in_game_id'] = data['in_game_id']
        payload['count'] = data.get('count', 1)
        detail_target = data['in_game_id']

    resp, status = gs_request('POST', '/api/tasks', json=payload)
    if status not in (200, 201):
        return jsonify({'error': resp.get('error', 'Failed to create delivery task')}), status

    detail = f"{kind} {detail_target} -> {username or 'server'}@server{server_id}"
    with db.get_db() as session:
        audit.record(session, current_user['user_id'], 'reward.give',
                     target=username or f"server{server_id}", detail=detail)

    return jsonify({'message': 'Delivery task created', 'task': resp.get('data')}), status


@admin_bp.route('/audit', methods=['GET'])
@moderator_required
def get_audit_log(current_user):
    """View audit log entries, newest first (moderator/admin only).

    Filterable by actor and action, because a log nobody can query is a log
    nobody reads. Both columns are already indexed for it.
    """
    try:
        limit, offset = paging.params()
        with db.get_db() as session:
            query = session.query(AuditLog)

            actor = request.args.get('actor')
            if actor:
                try:
                    query = query.filter(AuditLog.actor_user_id == int(actor))
                except (TypeError, ValueError):
                    return jsonify({'error': 'actor must be a user id'}), 400
            action = request.args.get('action')
            if action:
                query = query.filter(AuditLog.action == action)

            query = query.order_by(AuditLog.created_at.desc())
            entries, total = paging.page(query, limit, offset)
            return jsonify({
                'entries': [e.to_dict() for e in entries],
                'pagination': paging.meta(total, limit, offset)
            }), 200
    except Exception as e:
        logger.error(f"Get audit log error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/audit', methods=['DELETE'])
@admin_required
def clear_audit_log(current_user):
    """Delete audit entries (admin only).

    ``?older_than_days=N`` keeps the last N days and deletes what precedes
    them - the retention trim an operator actually wants, and the reason this
    exists: an audit log that only grows is a data-protection problem on a
    public server. Without it, everything goes.

    Admin only, never moderator: erasing the record of what staff did is a
    bigger power than anything else on this page. The clear is itself audited,
    and that entry is written *after* the delete, so it survives as evidence
    that the log was emptied, by whom, and how much went.
    """
    raw = request.args.get('older_than_days')
    cutoff = None
    if raw not in (None, ''):
        try:
            days = int(raw)
        except (TypeError, ValueError):
            return jsonify({'error': 'older_than_days must be a whole number'}), 400
        if days < 0:
            return jsonify({'error': 'older_than_days cannot be negative'}), 400
        cutoff = datetime.utcnow() - timedelta(days=days)

    try:
        with db.get_db() as session:
            query = session.query(AuditLog)
            if cutoff is not None:
                query = query.filter(AuditLog.created_at < cutoff)
            removed = query.delete(synchronize_session=False)

            scope = (f'older than {raw} day(s)' if cutoff is not None else 'all entries')
            audit.record(session, current_user['user_id'], 'audit.clear',
                         detail=f'removed {removed} entries ({scope})')
            return jsonify({'message': f'Removed {removed} entries', 'count': removed}), 200
    except Exception as e:
        logger.error(f"Clear audit log error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# How many Workshop items one request may carry. Matched to the manager's own
# limit; a collection is the way to add many at once and is a single entry.
MAX_MOD_ITEMS = 100


# ---------------------------------------------------------------------------
# Installation management (proxied to the game-server API)
#
# One SteamCMD install directory serves every server in the stack, and the
# Workshop content downloaded into it is shared the same way. So this is host
# state rather than server state, and it gets its own endpoints instead of
# hanging off a server id. What *is* per-server is only the selection, which
# stays on `/servers/<id>/mods`.
# ---------------------------------------------------------------------------

@admin_bp.route('/installation', methods=['GET'])
@moderator_required
def get_installation(current_user):
    """The state of the shared game install (moderator/admin only)."""
    payload, status = gs_request('GET', '/api/installation')
    if status != 200:
        return jsonify({'error': payload.get('error', 'Could not read the installation')}), status
    return jsonify(payload.get('data') or {}), 200


@admin_bp.route('/installation/update', methods=['POST'])
@admin_required
def queue_installation_update(current_user):
    """Queue a SteamCMD install/update of the game files (admin only).

    Admin rather than moderator: this replaces the binaries every server runs,
    and it takes long enough to hold up the task queue behind it.
    """
    data = request.get_json(silent=True) or {}
    task = {'action': 'update_server'}
    # Only forwarded when the caller actually chose a branch - the task treats
    # an explicit empty string as "public", which is not the same as "as
    # configured", and sending one by accident would silently switch branches.
    if 'beta' in data:
        task['beta'] = (data.get('beta') or '').strip()

    payload, status = gs_request('POST', '/api/tasks', json=task)
    if status not in (200, 201):
        return jsonify({'error': payload.get('error', 'Could not queue the update')}), status

    audit.record_standalone(current_user['user_id'], 'installation.update',
                            detail=(f"branch: {task['beta'] or 'public'}"
                                    if 'beta' in task else 'configured branch'))
    return jsonify({'message': 'Update queued', 'task': payload.get('data')}), 202


@admin_bp.route('/installation/uninstall', methods=['POST'])
@admin_required
def queue_installation_uninstall(current_user):
    """Queue a delete of the installed game files (admin only).

    Removes what SteamCMD installed so a clean or fresh install can follow.
    Server configs and saved worlds live in a separate tree and are never
    touched. Downloaded Workshop mods are kept unless the caller sends
    `keep_mods: false`. Admin rather than moderator for the same reason as the
    update: it changes the binaries every server runs.
    """
    data = request.get_json(silent=True) or {}
    task = {'action': 'uninstall_server'}
    # Only forwarded when the caller opts out of the default (keep the mods), so
    # the game-server task keeps ownership of the default.
    if data.get('keep_mods') is False:
        task['keep_mods'] = False

    payload, status = gs_request('POST', '/api/tasks', json=task)
    if status not in (200, 201):
        return jsonify({'error': payload.get('error', 'Could not queue the uninstall')}), status

    audit.record_standalone(current_user['user_id'], 'installation.uninstall',
                            detail=('including Workshop content'
                                    if task.get('keep_mods') is False
                                    else 'game files only'))
    return jsonify({'message': 'Uninstall queued', 'task': payload.get('data')}), 202


@admin_bp.route('/installation/app-info', methods=['POST'])
@admin_required
def queue_installation_app_info(current_user):
    """Queue a fetch of the app's branches and build ids from Steam (admin only)."""
    payload, status = gs_request('POST', '/api/tasks', json={'action': 'get_app_info'})
    if status not in (200, 201):
        return jsonify({'error': payload.get('error', 'Could not queue the fetch')}), status
    return jsonify({'message': 'Fetch queued', 'task': payload.get('data')}), 202


@admin_bp.route('/mods', methods=['GET'])
@moderator_required
def get_mods(current_user):
    """Every downloaded Workshop item, with what uses it (moderator/admin only)."""
    payload, status = gs_request('GET', '/api/mods')
    if status != 200:
        return jsonify({'error': payload.get('error', 'Could not read the mod library')}), status
    return jsonify({
        'mods': payload.get('data') or [],
        'mod_usage': payload.get('mod_usage') or {},
        # Null unless Steam could not be reached. "No title shown" because the
        # lookup failed is a different thing from "this item has no title".
        'metadata_error': payload.get('metadata_error'),
    }), 200


@admin_bp.route('/mods/preview', methods=['POST'])
@admin_required
def preview_mods(current_user):
    """What some pasted ids or Workshop URLs refer to, before downloading them.

    Admin only because it is the step before installing, and only an admin can
    install. Nothing is queued and nothing is written.
    """
    data = request.get_json(silent=True) or {}
    items = data.get('items')
    if isinstance(items, str):
        items = [items]
    items = [str(i).strip() for i in (items or []) if str(i).strip()]
    if not items:
        return jsonify({'error': 'Give at least one Workshop item id or URL'}), 400
    if len(items) > MAX_MOD_ITEMS:
        return jsonify({'error': f'Too many at once (limit {MAX_MOD_ITEMS})'}), 400

    payload, status = gs_request('POST', '/api/mods/preview', json={'items': items})
    if status != 200:
        return jsonify({'error': payload.get('error', 'Could not look those up')}), status
    return jsonify(payload.get('data') or {}), 200



@admin_bp.route('/mods', methods=['POST'])
@admin_required
def install_mods(current_user):
    """Queue a Workshop download for the given items (admin only).

    Accepts ids or Workshop page URLs; the manager resolves them, because the
    rule for what a valid item id looks like belongs on the side that builds the
    SteamCMD command line.
    """
    data = request.get_json(silent=True) or {}
    items = data.get('items')
    if isinstance(items, str):
        items = [items]
    items = [str(i).strip() for i in (items or []) if str(i).strip()]
    if not items:
        return jsonify({'error': 'Give at least one Workshop item id or URL'}), 400
    if len(items) > MAX_MOD_ITEMS:
        return jsonify({'error': f'Too many at once (limit {MAX_MOD_ITEMS})'}), 400

    payload, status = gs_request('POST', '/api/tasks', json={
        'action': 'download_workshop',
        'workshop_ids': items,
    })
    if status not in (200, 201):
        return jsonify({'error': payload.get('error', 'Could not queue the download')}), status

    audit.record_standalone(current_user['user_id'], 'mods.install',
                            detail=f"{len(items)} item(s): {', '.join(items[:10])}")
    return jsonify({'message': 'Download queued', 'task': payload.get('data')}), 202


@admin_bp.route('/mods/collections', methods=['GET'])
@moderator_required
def get_mod_collections(current_user):
    """Collections installed from, with the author's mod order (moderator/admin).

    Moderator rather than admin: applying a collection to a server is switching
    mods on, which a moderator may do. Installing one is still admin-only.
    """
    payload, status = gs_request('GET', '/api/mods/collections')
    if status != 200:
        return jsonify({'error': payload.get('error', 'Could not read collections')}), status
    return jsonify({'collections': payload.get('data') or []}), 200


@admin_bp.route('/mods/collections/<int:collection_id>', methods=['DELETE'])
@admin_required
def delete_mod_collection(current_user, collection_id):
    """Forget a collection (admin only). The mods it brought in are untouched."""
    payload, status = gs_request('DELETE', f'/api/mods/collections/{collection_id}')
    if status != 200:
        return jsonify({'error': payload.get('error', 'Could not forget it')}), status

    audit.record_standalone(current_user['user_id'], 'mods.collection_forget',
                            target=f'collection:{collection_id}')
    return jsonify({'message': payload.get('message', 'Collection forgotten')}), 200


@admin_bp.route('/mods/<int:item_id>', methods=['DELETE'])
@admin_required
def delete_mod(current_user, item_id):
    """Delete a downloaded Workshop item (admin only).

    The manager refuses while a server still lists the id, so a 409 here means
    "in use", not a conflict the panel can retry away.
    """
    payload, status = gs_request('DELETE', f'/api/mods/{item_id}')
    if status != 200:
        return jsonify({'error': payload.get('error', 'Could not remove the item')}), status

    audit.record_standalone(current_user['user_id'], 'mods.delete',
                            target=f'workshop:{item_id}')
    return jsonify({'message': payload.get('message', 'Workshop item removed')}), 200


# Comfortably above the manager's own 30s wiki timeout, so a slow first fetch
# resolves rather than being cut off half way.
ITEM_CATALOG_PROXY_TIMEOUT = 45


# ---------------------------------------------------------------------------
# In-game item catalog (proxied to the game-server API)
#
# Reference data for the reward item picker, so an item is chosen from a list
# instead of typed from memory. It is fetched and cached by the manager rather
# than here: the backend has no egress by design (`internal: true`), and giving
# it some so it could call a wiki would hand outbound network access to the
# service that handles authentication and untrusted input.
# ---------------------------------------------------------------------------

@admin_bp.route('/items', methods=['GET'])
@moderator_required
def get_item_catalog(current_user):
    """The in-game item catalog (moderator/admin only).

    Proxied to the manager, which is the only service with egress - the backend
    sits on an `internal: true` network and cannot resolve a hostname, let alone
    fetch a wiki page.

    `stale` is set when the cached copy could not be refreshed: the list is
    still usable, it is just older than we would like, and that is worth saying
    rather than either hiding or treating as a failure.
    """
    # Longer than the proxy default: a cold cache means the manager is fetching
    # a 600KB page from a wiki, and its own timeout for that is 30s. Timing out
    # at 10 would fail the first request of every deployment.
    payload, status = gs_request('GET', '/api/items', timeout=ITEM_CATALOG_PROXY_TIMEOUT)
    if status != 200:
        return jsonify({'error': payload.get('error', 'The item catalog is unavailable')}), status

    catalog = payload.get('data') or {}
    catalog['count'] = len(catalog.get('items') or [])
    catalog['stale'] = payload.get('stale')
    return jsonify(catalog), 200


@admin_bp.route('/items/refresh', methods=['POST'])
@admin_required
def refresh_item_catalog(current_user):
    """Re-fetch the catalog from the wiki (admin only).

    Admin because it reaches out to somebody else's server, and there is no
    reason to do it more than occasionally - the underlying page changes when
    the game does.
    """
    payload, status = gs_request('GET', '/api/items', params={'refresh': '1'},
                                 timeout=ITEM_CATALOG_PROXY_TIMEOUT)
    if status != 200:
        return jsonify({'error': payload.get('error', 'Could not refresh the item catalog')}), status

    catalog = payload.get('data') or {}
    count = len(catalog.get('items') or [])
    audit.record_standalone(current_user['user_id'], 'items.refresh',
                            detail=f"{count} item(s), "
                                   f"game {catalog.get('game_version') or 'unknown'}")
    return jsonify({
        'message': f'{count} items loaded',
        'game_version': catalog.get('game_version'),
        'fetched_at': catalog.get('fetched_at'),
        'stale': payload.get('stale'),
    }), 200


# ---------------------------------------------------------------------------
# Task management (proxied to the game-server API)
# ---------------------------------------------------------------------------

@admin_bp.route('/tasks', methods=['GET'])
@moderator_required
def get_tasks(current_user):
    """Get all tasks from game server (moderator/admin only)"""
    params = {}
    for key in ('status', 'limit', 'offset'):
        if request.args.get(key):
            params[key] = request.args.get(key)

    payload, status = gs_request('GET', '/api/tasks', params=params)
    if status != 200:
        return jsonify({'error': payload.get('error', 'Failed to fetch tasks')}), status
    # Normalize the game-server's {data: [...]} envelope to {tasks: [...]}.
    return jsonify({'tasks': payload.get('data', [])}), 200


@admin_bp.route('/tasks', methods=['POST'])
@admin_required
def create_task(current_user):
    """Create a task on the game server (admin only).

    Admin because the action is free-form: a moderator posting
    `{"action": "update_server"}` here would reinstall the game files and walk
    around every check on the endpoints that exist to gate exactly that.
    """
    data = request.get_json()

    if not data or not data.get('action'):
        return jsonify({'error': 'Task action is required'}), 400

    payload, status = gs_request('POST', '/api/tasks', json=data)
    if status not in (200, 201):
        return jsonify({'error': payload.get('error', 'Failed to create task')}), status
    return jsonify({
        'message': 'Task created successfully',
        'task': payload.get('data')
    }), status


@admin_bp.route('/tasks/<int:task_id>', methods=['GET'])
@moderator_required
def get_task(current_user, task_id):
    """Get one task, including its full result data (moderator/admin only)"""
    payload, status = gs_request('GET', f'/api/tasks/{task_id}')
    if status != 200:
        return jsonify({'error': payload.get('error', 'Task not found')}), status
    return jsonify({'task': payload.get('data')}), 200


@admin_bp.route('/tasks/<int:task_id>', methods=['DELETE'])
@moderator_required
def delete_task(current_user, task_id):
    """Delete a pending or completed task (moderator/admin only).

    The game-server refuses to delete a task that is mid-flight, so a 400 here
    means "it is still processing", not "bad request from the panel".
    """
    payload, status = gs_request('DELETE', f'/api/tasks/{task_id}')
    if status != 200:
        return jsonify({'error': payload.get('error', 'Failed to delete task')}), status

    audit.record_standalone(current_user['user_id'], 'task.delete',
                            target=f'task:{task_id}')
    return jsonify({'message': 'Task deleted successfully'}), 200


@admin_bp.route('/tasks', methods=['DELETE'])
@moderator_required
def clear_tasks(current_user):
    """Clear every pending and completed task (moderator/admin only).

    Tasks already being processed are left alone - the worker owns those.
    """
    payload, status = gs_request('DELETE', '/api/tasks')
    if status != 200:
        return jsonify({'error': payload.get('error', 'Failed to clear tasks')}), status

    count = payload.get('count')
    audit.record_standalone(current_user['user_id'], 'task.clear',
                            detail=f'cleared {count} task(s)' if count is not None else None)
    return jsonify({'message': 'Tasks cleared successfully', 'count': count}), 200


# ---------------------------------------------------------------------------
# Runtime settings
# ---------------------------------------------------------------------------

@admin_bp.route('/settings', methods=['GET'])
@admin_required
def get_settings(current_user):
    """Every runtime-editable setting with its effective value (admin only).

    Secrets report only whether they are set - the panel never needs the value
    back, and echoing it would put it in a browser and in logs.
    """
    try:
        return jsonify({'settings': settings.describe()}), 200
    except Exception as e:
        logger.error(f"Get settings error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/settings', methods=['PUT'])
@admin_required
def update_settings(current_user):
    """Override one or more settings (admin only).

    Only keys in the registry are accepted, so this cannot be used to write
    arbitrary rows. Values are never audited - one of them is a shared password.
    """
    data = request.get_json(silent=True) or {}
    unknown = [k for k in data if k not in settings.REGISTRY]
    if unknown:
        return jsonify({'error': f"Unknown setting(s): {', '.join(sorted(unknown))}"}), 400
    if not data:
        return jsonify({'error': 'No settings provided'}), 400

    try:
        with db.get_db() as session:
            for key, value in data.items():
                try:
                    settings.set_value(session, key, value, current_user['user_id'])
                except ValueError as e:
                    return jsonify({'error': str(e)}), 400

            audit.record(session, current_user['user_id'], 'settings.update',
                         detail=f"changed: {', '.join(sorted(data.keys()))}")

        settings.reset_cache()
        return jsonify({'message': 'Settings updated', 'settings': settings.describe()}), 200
    except Exception as e:
        logger.error(f"Update settings error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/settings/test-mail', methods=['POST'])
@admin_required
def test_mail(current_user):
    """Send a test message to the caller's own address (admin only).

    Mail is the one setting whose failure is invisible: a wrong password means
    verification and reset messages stop arriving, and nobody finds out until
    somebody cannot get back into their account. This is how an admin finds out
    in ten seconds instead.

    Sent to their own address rather than a typed one, so this cannot be used
    to bounce mail at a stranger.
    """
    try:
        with db.get_db() as session:
            user = session.query(User).filter_by(id=current_user['user_id']).first()
            if not user or not user.email:
                return jsonify({'error': 'Your account has no email address'}), 400
            address = user.email
            username = user.username

        if not mailer.is_configured():
            return jsonify({
                'error': 'No mail server is configured, here or on the game-server'
            }), 409

        sent = mailer.send(
            address,
            'Safezone mail test',
            f'Hi {username},\n\n'
            f'Your mail settings work. This was sent from the admin panel to '
            f'confirm that verification and password-reset messages will '
            f'arrive.\n'
        )
        audit.record_standalone(current_user['user_id'], 'settings.test_mail',
                                detail='delivered' if sent else 'failed')
        if not sent:
            return jsonify({'error': 'The mail server refused it - check the '
                                     'backend log for what it said'}), 502
        return jsonify({'message': f'Sent to {address}. Check your inbox.'}), 200
    except Exception as e:
        logger.error(f"Test mail error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# Scheduled jobs
# ---------------------------------------------------------------------------

@admin_bp.route('/jobs', methods=['GET'])
@admin_required
def get_jobs(current_user):
    """Every recurring job, with what it last did (admin only)."""
    from src.models.scheduled_job import ScheduledJob

    try:
        with db.get_db() as session:
            rows = session.query(ScheduledJob).order_by(ScheduledJob.kind.asc()).all()
            return jsonify({
                'jobs': [r.to_dict() for r in rows],
                'kinds': jobs.describe()
            }), 200
    except Exception as e:
        logger.error(f"Get jobs error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/jobs/<int:job_id>', methods=['PUT'])
@admin_required
def update_job(current_user, job_id):
    """Enable/disable a job, change its interval, or set its params (admin only)."""
    from src.models.scheduled_job import ScheduledJob

    data = request.get_json(silent=True) or {}

    # Validated up front: an error returned mid-way would still commit whatever
    # had already been assigned, so a bad interval would silently enable the job.
    interval = None
    if 'interval_seconds' in data:
        try:
            interval = int(data['interval_seconds'])
        except (TypeError, ValueError):
            return jsonify({'error': 'interval_seconds must be a whole number'}), 400
        # A minute is the floor: anything tighter is a busy loop against the
        # database, not a schedule.
        if interval < 60:
            return jsonify({'error': 'interval_seconds must be at least 60'}), 400
    if 'params' in data and data['params'] is not None and not isinstance(data['params'], dict):
        return jsonify({'error': 'params must be an object'}), 400

    try:
        with db.get_db() as session:
            row = session.query(ScheduledJob).filter_by(id=job_id).first()
            if not row:
                return jsonify({'error': 'Job not found'}), 404

            changed = []
            if 'enabled' in data:
                row.enabled = bool(data['enabled'])
                changed.append('enabled')
                if row.enabled and row.next_run_at is None:
                    row.next_run_at = datetime.utcnow()
            if interval is not None:
                row.interval_seconds = interval
                changed.append('interval_seconds')
            if 'params' in data:
                row.params = data['params']
                changed.append('params')

            audit.record(session, current_user['user_id'], 'job.update',
                         target=f'job:{row.kind}',
                         detail=f"changed: {', '.join(changed) or 'nothing'}")
            return jsonify({'message': 'Job updated', 'job': row.to_dict()}), 200
    except Exception as e:
        logger.error(f"Update job error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/jobs/<int:job_id>/run', methods=['POST'])
@admin_required
def run_job_now(current_user, job_id):
    """Ask for a job to run on the next tick (admin only).

    Deliberately does not run it inline: jobs can be slow, and a request that
    blocks on one would tie up a worker and time out in the browser. The
    scheduler picks it up within its tick.
    """
    from src.models.scheduled_job import ScheduledJob

    try:
        with db.get_db() as session:
            row = session.query(ScheduledJob).filter_by(id=job_id).first()
            if not row:
                return jsonify({'error': 'Job not found'}), 404
            if not row.enabled:
                return jsonify({'error': 'That job is disabled'}), 409

            row.next_run_at = datetime.utcnow()
            audit.record(session, current_user['user_id'], 'job.run',
                         target=f'job:{row.kind}')
            return jsonify({'message': f'{row.kind} will run shortly'}), 200
    except Exception as e:
        logger.error(f"Run job error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/box-pools/<int:entry_id>', methods=['PUT'])
@admin_required
def update_box_pool(current_user, entry_id):
    """Change a pool entry's drop weight and/or item quantity (admin only)."""
    data = request.get_json(silent=True) or {}

    weight = None
    if 'weight' in data:
        try:
            weight = float(data['weight'])
        except (TypeError, ValueError):
            return jsonify({'error': 'weight must be a number'}), 400
        if weight < 0 or weight > 1000:
            return jsonify({'error': 'weight must be between 0 and 1000'}), 400

    count = None
    if 'count' in data:
        count = data['count']
        count_error = validate_item_count(count)
        if count_error:
            return jsonify({'error': count_error}), 400

    if weight is None and count is None:
        return jsonify({'error': 'weight or count is required'}), 400

    try:
        with db.get_db() as session:
            entry = session.query(BoxLootPool).filter_by(id=entry_id).first()
            if not entry:
                return jsonify({'error': 'Pool entry not found'}), 404
            box = session.get(Box, entry.box_id)
            where = f"the '{box.name if box else entry.box_id}' pool"
            changes = []
            if weight is not None:
                changes.append(f"weight {entry.weight} -> {weight}")
                entry.weight = weight
            if count is not None:
                changes.append(f"count {entry.count} -> {count}")
                entry.count = count
            audit.record(session, current_user['user_id'], 'box_pool.update',
                         target=f'pool:{entry_id}',
                         detail=f"{', '.join(changes)} in {where}")
            return jsonify({'message': 'Pool entry updated', 'pool': entry.to_dict()}), 200
    except Exception as e:
        logger.error(f"Update box pool error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# Events (what grants a box, and which boxes take part)
# ---------------------------------------------------------------------------

def _event_payload(session, event, boxes_by_id):
    """One event with its box line-up and each box's pick chance."""
    entries = (session.query(EventBox)
               .filter_by(event_id=event.id).order_by(EventBox.id).all())
    total = sum(e.weight for e in entries
                if e.weight > 0 and boxes_by_id.get(e.box_id))
    boxes = []
    for e in entries:
        box = boxes_by_id.get(e.box_id)
        droppable = bool(box and e.weight > 0)
        boxes.append({
            'id': e.id,
            'box_id': e.box_id,
            'name': box.name if box else f'#{e.box_id}',
            'draws': box.draws if box else 0,
            'weight': e.weight,
            'pick_chance': (e.weight / total) if (droppable and total > 0) else 0.0,
        })
    return {**event.to_dict(), 'boxes': boxes}


@admin_bp.route('/events', methods=['GET'])
@moderator_required
def get_events(current_user):
    """Every event with its box line-up. System events first, then customs."""
    try:
        with db.get_db() as session:
            boxes_by_id = {b.id: b for b in session.query(Box).all()}
            ordered = (session.query(Event)
                       .order_by(Event.system.desc(), Event.type, Event.id).all())
            return jsonify({'events': [_event_payload(session, e, boxes_by_id)
                                       for e in ordered]}), 200
    except Exception as e:
        logger.error(f"Get events error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


def _parse_dt(value):
    """Parse an ISO datetime (accepting a trailing Z), or None. Raises ValueError."""
    if value in (None, ''):
        return None
    return datetime.fromisoformat(str(value).replace('Z', '+00:00')).replace(tzinfo=None)


@admin_bp.route('/events', methods=['POST'])
@admin_required
def create_event(current_user):
    """Create a custom event (admin only).

    Only custom events can be created; the daily and weekly-bonus events are
    seeded once and edited in place.
    """
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name is required'}), 400
    if len(name) > 80:
        return jsonify({'error': 'name must be 80 characters or fewer'}), 400

    cadence = data.get('cadence', Event.CADENCE_DAILY)
    if cadence not in (Event.CADENCE_DAILY, Event.CADENCE_ONCE):
        return jsonify({'error': "cadence must be 'daily' or 'once'"}), 400

    try:
        starts_at = _parse_dt(data.get('starts_at'))
        ends_at = _parse_dt(data.get('ends_at'))
    except (ValueError, TypeError):
        return jsonify({'error': 'starts_at and ends_at must be ISO datetimes'}), 400
    if starts_at and ends_at and ends_at <= starts_at:
        return jsonify({'error': 'ends_at must be after starts_at'}), 400

    try:
        with db.get_db() as session:
            event = Event(
                type=Event.TYPE_CUSTOM,
                name=name,
                description=(data.get('description') or '').strip() or None,
                enabled=bool(data.get('enabled', True)),
                cadence=cadence,
                starts_at=starts_at,
                ends_at=ends_at,
                system=False,
            )
            session.add(event)
            session.flush()
            audit.record(session, current_user['user_id'], 'event.create',
                         target=f'event:{event.id}', detail=f"'{name}' ({cadence})")
            return jsonify({'message': 'Event created', 'event': event.to_dict()}), 201
    except Exception as e:
        logger.error(f"Create event error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/events/<int:event_id>', methods=['PUT'])
@admin_required
def update_event(current_user, event_id):
    """Edit an event (admin only).

    Every event can be enabled/disabled and renamed. The window and cadence
    belong to custom events only; the two system events ignore them.
    """
    data = request.get_json(silent=True) or {}
    try:
        with db.get_db() as session:
            event = session.get(Event, event_id)
            if not event:
                return jsonify({'error': 'Event not found'}), 404

            changed = []
            if 'name' in data:
                name = (data.get('name') or '').strip()
                if not name:
                    return jsonify({'error': 'name cannot be empty'}), 400
                if len(name) > 80:
                    return jsonify({'error': 'name must be 80 characters or fewer'}), 400
                event.name = name
                changed.append('name')
            if 'description' in data:
                event.description = (data.get('description') or '').strip() or None
                changed.append('description')
            if 'enabled' in data:
                event.enabled = bool(data['enabled'])
                changed.append(f'enabled={event.enabled}')

            if event.type == Event.TYPE_CUSTOM:
                if 'cadence' in data:
                    if data['cadence'] not in (Event.CADENCE_DAILY, Event.CADENCE_ONCE):
                        return jsonify({'error': "cadence must be 'daily' or 'once'"}), 400
                    event.cadence = data['cadence']
                    changed.append('cadence')
                try:
                    if 'starts_at' in data:
                        event.starts_at = _parse_dt(data.get('starts_at'))
                        changed.append('starts_at')
                    if 'ends_at' in data:
                        event.ends_at = _parse_dt(data.get('ends_at'))
                        changed.append('ends_at')
                except (ValueError, TypeError):
                    return jsonify({'error': 'starts_at and ends_at must be ISO datetimes'}), 400
                if event.starts_at and event.ends_at and event.ends_at <= event.starts_at:
                    return jsonify({'error': 'ends_at must be after starts_at'}), 400

            audit.record(session, current_user['user_id'], 'event.update',
                         target=f'event:{event_id}', detail=', '.join(changed) or 'nothing')
            result = event.to_dict()
            return jsonify({'message': 'Event updated', 'event': result}), 200
    except Exception as e:
        logger.error(f"Update event error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/events/<int:event_id>', methods=['DELETE'])
@admin_required
def delete_event(current_user, event_id):
    """Delete a custom event (admin only). System events cannot be deleted."""
    try:
        with db.get_db() as session:
            event = session.get(Event, event_id)
            if not event:
                return jsonify({'error': 'Event not found'}), 404
            if event.system:
                return jsonify({'error': 'The daily and weekly bonus events cannot be '
                                         'deleted. Disable it instead.'}), 409
            name = event.name
            # event_boxes cascade; already-granted user_boxes keep their history
            # with event_id set null.
            session.delete(event)
            audit.record(session, current_user['user_id'], 'event.delete',
                         target=f'event:{event_id}', detail=f"'{name}'")
            return jsonify({'message': 'Event deleted'}), 200
    except Exception as e:
        logger.error(f"Delete event error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/events/<int:event_id>/boxes', methods=['POST'])
@admin_required
def add_event_box(current_user, event_id):
    """Attach a box to an event with a pick weight (admin only)."""
    data = request.get_json(silent=True) or {}
    box_id = data.get('box_id')
    if not box_id:
        return jsonify({'error': 'box_id is required'}), 400
    weight = data.get('weight', 1)
    try:
        weight = float(weight)
    except (TypeError, ValueError):
        return jsonify({'error': 'weight must be a number'}), 400
    if weight < 0 or weight > 1000:
        return jsonify({'error': 'weight must be between 0 and 1000'}), 400

    try:
        with db.get_db() as session:
            event = session.get(Event, event_id)
            if not event:
                return jsonify({'error': 'Event not found'}), 404
            box = session.get(Box, box_id)
            if not box:
                return jsonify({'error': 'Box not found'}), 404
            if session.query(EventBox).filter_by(event_id=event_id, box_id=box_id).first():
                return jsonify({'error': 'That box is already in this event'}), 409
            entry = EventBox(event_id=event_id, box_id=box_id, weight=weight)
            session.add(entry)
            session.flush()
            audit.record(session, current_user['user_id'], 'event.box.add',
                         target=f'event:{event_id}',
                         detail=f"'{box.name}' at weight {weight}")
            return jsonify({'message': 'Box added to event', 'event_box': entry.to_dict()}), 201
    except Exception as e:
        logger.error(f"Add event box error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/events/<int:event_id>/boxes/<int:entry_id>', methods=['PUT'])
@admin_required
def update_event_box(current_user, event_id, entry_id):
    """Change a box's pick weight within an event (admin only)."""
    data = request.get_json(silent=True) or {}
    if 'weight' not in data:
        return jsonify({'error': 'weight is required'}), 400
    try:
        weight = float(data['weight'])
    except (TypeError, ValueError):
        return jsonify({'error': 'weight must be a number'}), 400
    if weight < 0 or weight > 1000:
        return jsonify({'error': 'weight must be between 0 and 1000'}), 400

    try:
        with db.get_db() as session:
            entry = session.query(EventBox).filter_by(id=entry_id, event_id=event_id).first()
            if not entry:
                return jsonify({'error': 'That box is not in this event'}), 404
            entry.weight = weight
            audit.record(session, current_user['user_id'], 'event.box.reweight',
                         target=f'event:{event_id}', detail=f"box {entry.box_id} -> {weight}")
            return jsonify({'message': 'Weight updated', 'event_box': entry.to_dict()}), 200
    except Exception as e:
        logger.error(f"Update event box error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/events/<int:event_id>/boxes/<int:entry_id>', methods=['DELETE'])
@admin_required
def delete_event_box(current_user, event_id, entry_id):
    """Remove a box from an event (admin only)."""
    try:
        with db.get_db() as session:
            entry = session.query(EventBox).filter_by(id=entry_id, event_id=event_id).first()
            if not entry:
                return jsonify({'error': 'That box is not in this event'}), 404
            box_id = entry.box_id
            session.delete(entry)
            audit.record(session, current_user['user_id'], 'event.box.remove',
                         target=f'event:{event_id}', detail=f"box {box_id}")
            return jsonify({'message': 'Box removed from event'}), 200
    except Exception as e:
        logger.error(f"Delete event box error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# Reports and appeals
# ---------------------------------------------------------------------------

@admin_bp.route('/reports', methods=['GET'])
@moderator_required
def get_reports(current_user):
    """The report and appeal queue. Open items first, oldest first."""
    from src.models.report import Report

    try:
        limit, offset = paging.params()
        with db.get_db() as session:
            query = session.query(Report)

            status = request.args.get('status')
            if status:
                query = query.filter_by(status=status)
            kind = request.args.get('kind')
            if kind:
                query = query.filter_by(kind=kind)

            # Open first, then oldest first: somebody has been waiting.
            query = query.order_by(
                (Report.status != Report.STATUS_OPEN),
                Report.created_at.asc()
            )
            rows, total = paging.page(query, limit, offset)

            open_count = (session.query(Report)
                          .filter_by(status=Report.STATUS_OPEN)
                          .count())

            return jsonify({
                'reports': [r.to_dict() for r in rows],
                'open': open_count,
                'pagination': paging.meta(total, limit, offset)
            }), 200
    except Exception as e:
        logger.error(f"Get reports error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/reports/<int:report_id>', methods=['POST'])
@moderator_required
def resolve_report(current_user, report_id):
    """Close a report or appeal with an explanation (moderator/admin only).

    The explanation is required and is shown to the person who filed it: a
    resolution nobody explains is indistinguishable from being ignored, which is
    the thing having a report process was meant to fix.
    """
    from src.models.report import Report

    data = request.get_json(silent=True) or {}
    status = (data.get('status') or '').strip()
    resolution = (data.get('resolution') or '').strip()

    if status not in (Report.STATUS_RESOLVED, Report.STATUS_DISMISSED):
        return jsonify({'error': 'status must be resolved or dismissed'}), 400
    if not resolution:
        return jsonify({'error': 'Say what you decided - the reporter sees this'}), 400

    try:
        with db.get_db() as session:
            report = session.query(Report).filter_by(id=report_id).first()
            if not report:
                return jsonify({'error': 'Not found'}), 404
            if report.status != Report.STATUS_OPEN:
                return jsonify({'error': 'That has already been answered'}), 409

            report.status = status
            report.resolution = resolution
            report.reviewed_by = current_user['user_id']
            report.reviewed_at = datetime.utcnow()

            label = 'appeal' if report.kind == Report.KIND_APPEAL else 'report'
            audit.record(session, current_user['user_id'], f'{label}.{status}',
                         target=f'report:{report_id}',
                         detail=resolution[:200])
            notify.send(session, report.reporter_user_id, Notification.KIND_MODERATION,
                        f'Your {label} was answered',
                        body=resolution,
                        link='/reports')

            return jsonify({'message': 'Answered', 'report': report.to_dict()}), 200
    except Exception as e:
        logger.error(f"Resolve report error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# Alert channels (Discord webhooks, the staff feed, ops mail)
# ---------------------------------------------------------------------------

def _channel_payload(session, data, existing=None):
    """Validate a create/update body. Returns ``(values, error)``.

    On update, an absent key means "leave it alone" - notably a webhook's URL,
    which the panel never gets back in full and so cannot resubmit.
    """
    values = {}
    kind = (data.get('kind') or (existing.kind if existing else '')).strip()

    if existing is None:
        if kind not in AlertChannel.KINDS:
            return None, f"kind must be one of: {', '.join(AlertChannel.KINDS)}"
        # The staff feed is one destination by definition - it always means
        # "every moderator and admin" - so a second row could only ever produce
        # duplicate notifications.
        if kind == AlertChannel.KIND_INAPP:
            existing_inapp = (session.query(AlertChannel)
                              .filter_by(kind=AlertChannel.KIND_INAPP).first())
            if existing_inapp:
                return None, 'The staff feed is already set up; edit that one'
        values['kind'] = kind
    elif data.get('kind') and data['kind'] != existing.kind:
        # Changing kind would mean the target means something else entirely.
        return None, 'A channel cannot change kind - remove it and add the other'

    if 'name' in data or existing is None:
        name = (data.get('name') or '').strip()
        if not name:
            return None, 'A name is required - it is how you tell channels apart'
        values['name'] = name[:64]

    if 'target' in data or existing is None:
        target = (data.get('target') or '').strip()
        keep = existing is not None and not target
        if kind == AlertChannel.KIND_WEBHOOK:
            if not keep and not channels.is_discord_url(target):
                return None, ('That is not a Discord webhook URL. Copy it from the '
                              'channel Integrations settings; it starts with '
                              'https://discord.com/api/webhooks/')
            if not keep:
                values['target'] = target
        elif kind == AlertChannel.KIND_EMAIL:
            if not keep:
                addresses, error = channels.valid_addresses(target)
                if error:
                    return None, error
                values['target'] = ', '.join(addresses)
        else:
            values['target'] = None  # the inbox needs no address

    if 'events' in data or existing is None:
        events = data.get('events') or []
        if not isinstance(events, list):
            return None, 'events must be a list'
        unknown = [e for e in events if e not in alerting.EVENTS]
        if unknown:
            return None, f"Unknown event(s): {', '.join(sorted(unknown))}"
        values['events'] = sorted(set(events))

    if 'server_ids' in data:
        server_ids = data.get('server_ids') or []
        if not isinstance(server_ids, list):
            return None, 'server_ids must be a list'
        try:
            values['server_ids'] = sorted({int(s) for s in server_ids})
        except (TypeError, ValueError):
            return None, 'server_ids must be whole numbers'

    if 'enabled' in data:
        values['enabled'] = bool(data['enabled'])

    return values, None


@admin_bp.route('/alerts', methods=['GET'])
@admin_required
def get_alert_channels(current_user):
    """Every channel, the event catalog, and whether events are flowing.

    The queue status is here rather than left to guesswork: game events reach
    their channels through the scheduler, so "the scheduler is not running" and
    "nobody has joined" look identical from the panel unless it is said out
    loud. Same for mail, which needs a relay that may not be configured.
    """
    try:
        with db.get_db() as session:
            rows = (session.query(AlertChannel)
                    .order_by(AlertChannel.kind.asc(), AlertChannel.id.asc())
                    .all())
            return jsonify({
                'channels': [r.to_dict() for r in rows],
                'events': alerting.describe(),
                'pump': alerting.pump_status(),
                'mail_configured': mailer.is_configured(),
            }), 200
    except Exception as e:
        logger.error(f"Get alert channels error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/alerts/channels', methods=['POST'])
@admin_required
def create_alert_channel(current_user):
    """Add a channel (admin only)."""
    data = request.get_json(silent=True) or {}

    try:
        with db.get_db() as session:
            values, error = _channel_payload(session, data)
            if error:
                return jsonify({'error': error}), 400

            row = AlertChannel(created_by=current_user['user_id'], **values)
            session.add(row)
            session.flush()
            # A webhook URL is a bearer secret: never audited, never returned
            # whole. The name is what identifies it in the log.
            audit.record(session, current_user['user_id'], 'alert_channel.create',
                         target=f'alert_channel:{row.id}',
                         detail=f"{row.kind} '{row.name}': "
                                f"{', '.join(row.events or []) or 'no events'}")
            return jsonify({'message': 'Channel added', 'channel': row.to_dict()}), 201
    except Exception as e:
        logger.error(f"Create alert channel error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/alerts/channels/<int:channel_id>', methods=['PUT'])
@admin_required
def update_alert_channel(current_user, channel_id):
    """Change a channel's name, destination, subscriptions or servers (admin only)."""
    data = request.get_json(silent=True) or {}

    try:
        with db.get_db() as session:
            row = session.query(AlertChannel).filter_by(id=channel_id).first()
            if not row:
                return jsonify({'error': 'Channel not found'}), 404

            values, error = _channel_payload(session, data, existing=row)
            if error:
                return jsonify({'error': error}), 400

            for key, value in values.items():
                setattr(row, key, value)
            # Re-enabling by hand, or fixing the destination, is somebody saying
            # "try again"; the failure count that switched it off should not
            # still be counting against it.
            if values.get('enabled') or 'target' in values:
                row.failure_count = 0
                row.last_error = None

            audit.record(session, current_user['user_id'], 'alert_channel.update',
                         target=f'alert_channel:{row.id}',
                         detail=f"changed: {', '.join(sorted(values.keys())) or 'nothing'}")
            return jsonify({'message': 'Channel updated', 'channel': row.to_dict()}), 200
    except Exception as e:
        logger.error(f"Update alert channel error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/alerts/channels/<int:channel_id>', methods=['DELETE'])
@admin_required
def delete_alert_channel(current_user, channel_id):
    """Remove a channel (admin only). Nothing changes at the destination."""
    try:
        with db.get_db() as session:
            row = session.query(AlertChannel).filter_by(id=channel_id).first()
            if not row:
                return jsonify({'error': 'Channel not found'}), 404
            name, kind = row.name, row.kind
            session.delete(row)
            audit.record(session, current_user['user_id'], 'alert_channel.delete',
                         target=f'alert_channel:{channel_id}', detail=f'{kind}: {name}')
            return jsonify({'message': 'Channel removed'}), 200
    except Exception as e:
        logger.error(f"Delete alert channel error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/alerts/channels/<int:channel_id>/test', methods=['POST'])
@admin_required
def test_alert_channel(current_user, channel_id):
    """Send a sample message and report what happened (admin only).

    Synchronous, unlike a real event: somebody who has just pasted a URL or
    typed an address is waiting to find out whether it was the right one.
    """
    try:
        ok, error = alerting.send_test(channel_id)
        audit.record_standalone(current_user['user_id'], 'alert_channel.test',
                                target=f'alert_channel:{channel_id}',
                                detail='delivered' if ok else f'failed: {error}')
        if not ok:
            return jsonify({'error': error or 'The test message was not delivered'}), 502
        return jsonify({'message': 'Test message delivered'}), 200
    except Exception as e:
        logger.error(f"Test alert channel error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# The staff feed (what actually fired, and how far each person has read)
# ---------------------------------------------------------------------------

@admin_bp.route('/staff-feed', methods=['GET'])
@moderator_required
def get_staff_feed(current_user):
    """Alerts that reached the staff feed, newest first.

    Moderator rather than admin, because this is the replacement for the
    notifications moderators already received - restricting it now would take
    something away rather than reorganise it. The channel *configuration* stays
    admin-only; reading what happened is not the same power as changing where it
    goes.

    The event catalog comes back alongside the rows so this screen renders
    labels and groups without calling the admin-only `/alerts` endpoint.
    """
    from src.models.staff_alert import StaffAlert

    try:
        limit, offset = paging.params(default_limit=25)
        event = request.args.get('event')
        if event and event not in alerting.EVENTS:
            return jsonify({'error': 'Unknown event'}), 400

        with db.get_db() as session:
            query = session.query(StaffAlert)
            if event:
                query = query.filter(StaffAlert.event == event)
            query = query.order_by(StaffAlert.created_at.desc(), StaffAlert.id.desc())
            rows, total = paging.page(query, limit, offset)

            marker = _staff_read_marker(session, current_user['user_id'])
            return jsonify({
                'alerts': [r.to_dict() for r in rows],
                'unread': _staff_unread(session, marker),
                'read_at': marker.isoformat() if marker else None,
                'events': alerting.describe(),
                'pagination': paging.meta(total, limit, offset),
            }), 200
    except Exception as e:
        logger.error(f"Get staff feed error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


def _staff_read_marker(session, user_id):
    """How far this account has read the feed, or None if it never has."""
    row = session.get(User, user_id)
    return row.staff_alerts_read_at if row else None


def _staff_unread(session, marker):
    """How many alerts are newer than a read marker."""
    from src.models.staff_alert import StaffAlert

    query = session.query(StaffAlert)
    if marker is not None:
        query = query.filter(StaffAlert.created_at > marker)
    return query.count()


@admin_bp.route('/staff-feed/unread-count', methods=['GET'])
@moderator_required
def staff_feed_unread(current_user):
    """Just the badge number - polled often, so it stays cheap."""
    try:
        with db.get_db() as session:
            marker = _staff_read_marker(session, current_user['user_id'])
            return jsonify({'unread': _staff_unread(session, marker)}), 200
    except Exception as e:
        logger.error(f"Staff feed unread count error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/staff-feed/read', methods=['POST'])
@moderator_required
def mark_staff_feed_read(current_user):
    """Mark the feed read up to now.

    One write per person per visit, rather than one per message: the feed is
    shared, so "read" is a position in it and not a flag on every row. Stamped
    with the server's clock rather than the newest row's, so an alert that
    lands between the page rendering and this call is still counted as unread.
    """
    try:
        with db.get_db() as session:
            user = session.get(User, current_user['user_id'])
            if not user:
                return jsonify({'error': 'Account not found'}), 404
            user.staff_alerts_read_at = datetime.utcnow()
            return jsonify({'message': 'Feed marked read',
                            'read_at': user.staff_alerts_read_at.isoformat()}), 200
    except Exception as e:
        logger.error(f"Mark staff feed read error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

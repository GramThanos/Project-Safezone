"""Admin panel routes.

User management is handled locally (backend owns the `users` table). Server and
task operations are proxied to the game-server API, which owns those tables.
"""
import logging
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from src.database import db
from src.models.user import User
from src.models.character import Character
from src.models.claim_request import ClaimRequest
from src.models.reward import Reward
from src.models.box_loot_pool import BoxLootPool
from src.models.audit_log import AuditLog
from src.models.notification import Notification
from src.models.ban import Ban
from src.models.alert_channel import AlertChannel
from src.middleware.auth import moderator_required, admin_required
from src.utils.game_server import gs_request
from src.utils.redis_utils import apply_live_state
from src.utils import (loot, audit, settings, mailer, paging, notify, jobs, moderation,
                       box_types, alerting, channels)
from src.utils.actions import fetch_catalog, role_allows, validate_action

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

            return jsonify({
                'users': [u.to_dict() for u in users],
                'pagination': paging.meta(total, limit, offset)
            }), 200
    except Exception as e:
        logger.error(f"Get users error: {e}")
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
# Loot box pool configuration (which rewards each box size can contain)
# ---------------------------------------------------------------------------

@admin_bp.route('/box-pools', methods=['GET'])
@moderator_required
def get_box_pools(current_user):
    """List box loot pool entries (with reward details), optionally per size."""
    try:
        size = request.args.get('size')
        with db.get_db() as session:
            query = session.query(BoxLootPool)
            if size:
                query = query.filter_by(size=size)
            entries = query.all()
            rewards_by_id = {r.id: r for r in session.query(Reward).all()}
            result = []
            for e in entries:
                row = e.to_dict()
                reward = rewards_by_id.get(e.reward_id)
                row['reward'] = reward.to_dict() if reward else None
                result.append(row)

            # Pool health, so an empty pool is something an admin is told about
            # rather than something a player discovers by failing to open a box.
            health = []
            all_entries = session.query(BoxLootPool).all()
            for box_size, spec in box_types.all_types().items():
                mine = [e for e in all_entries if e.size == box_size]
                live = [e for e in mine
                        if (rewards_by_id.get(e.reward_id) is not None
                            and rewards_by_id[e.reward_id].active
                            and (e.weight or 0) > 0)]
                health.append({
                    'size': box_size,
                    'label': spec.get('label', box_size.title()),
                    'draws': spec.get('draws', 0),
                    'entries': len(mine),
                    'droppable': len(live),
                    # A box drawing more than its pool holds still works (it
                    # repeats), but it is thin and worth flagging.
                    'thin': 0 < len(live) < spec.get('draws', 0),
                    'empty': len(live) == 0,
                })

            return jsonify({'pools': result, 'health': health}), 200
    except Exception as ex:
        logger.error(f"Get box pools error: {ex}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/box-pools', methods=['POST'])
@admin_required
def add_box_pool(current_user):
    """Add a reward to a box size's loot pool (admin only)."""
    data = request.get_json() or {}
    size = data.get('size')
    reward_id = data.get('reward_id')
    if size not in box_types.all_types():
        return jsonify({'error': 'Invalid box size'}), 400
    if not reward_id:
        return jsonify({'error': 'reward_id is required'}), 400

    weight = data.get('weight', 1)
    try:
        weight = float(weight)
    except (TypeError, ValueError):
        return jsonify({'error': 'weight must be a number'}), 400
    if weight < 0 or weight > 1000:
        return jsonify({'error': 'weight must be between 0 and 1000'}), 400
    try:
        with db.get_db() as session:
            reward = session.query(Reward).filter_by(id=reward_id).first()
            if not reward:
                return jsonify({'error': 'Reward not found'}), 404
            existing = session.query(BoxLootPool).filter_by(size=size, reward_id=reward_id).first()
            if existing:
                return jsonify({'error': 'Reward already in this pool'}), 409
            entry = BoxLootPool(size=size, reward_id=reward_id, weight=weight)
            session.add(entry)
            session.flush()
            audit.record(session, current_user['user_id'], 'box_pool.add',
                         target=f'pool:{entry.id}',
                         detail=f"'{reward.name}' added to the {size} pool at weight {weight}")
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
            size = entry.size
            reward = session.query(Reward).filter_by(id=entry.reward_id).first()
            session.delete(entry)
            audit.record(session, current_user['user_id'], 'box_pool.remove',
                         target=f'pool:{entry_id}',
                         detail=f"'{reward.name if reward else entry_id}' removed from the {size} pool")
            return jsonify({'message': 'Removed from pool'}), 200
    except Exception as ex:
        logger.error(f"Delete box pool error: {ex}")
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
    """Change a pool entry's drop weight (admin only)."""
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
            entry = session.query(BoxLootPool).filter_by(id=entry_id).first()
            if not entry:
                return jsonify({'error': 'Pool entry not found'}), 404
            previous = entry.weight
            entry.weight = weight
            audit.record(session, current_user['user_id'], 'box_pool.reweight',
                         target=f'pool:{entry_id}',
                         detail=f"{previous} -> {weight} in the {entry.size} pool")
            return jsonify({'message': 'Weight updated', 'pool': entry.to_dict()}), 200
    except Exception as e:
        logger.error(f"Update box pool error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# Box types (how likely each size is, and how much it gives)
# ---------------------------------------------------------------------------

@admin_bp.route('/box-types', methods=['GET'])
@moderator_required
def get_box_types(current_user):
    """Every box size with its draw count and daily-roll weight."""
    from src.models.box_type import BoxType

    try:
        with db.get_db() as session:
            rows = session.query(BoxType).all()
            if not rows:
                # Seed lazily, so a database created before this table still works.
                box_types.seed(session)
                session.flush()
                rows = session.query(BoxType).all()

            total = sum(r.weight for r in rows if r.active and r.weight > 0)
            return jsonify({
                'box_types': [
                    dict(r.to_dict(),
                         # Weight is relative; the resulting chance is what an
                         # operator actually wants to reason about.
                         daily_chance=(r.weight / total if total > 0 and r.active else 0.0))
                    for r in rows
                ]
            }), 200
    except Exception as e:
        logger.error(f"Get box types error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/box-types/<string:size>', methods=['PUT'])
@admin_required
def update_box_type(current_user, size):
    """Retune a box size (admin only)."""
    from src.models.box_type import BoxType

    data = request.get_json(silent=True) or {}

    # Validated before anything is assigned: an error return still commits, so a
    # bad weight would otherwise apply the new draw count and report failure.
    draws = weight = None
    if 'draws' in data:
        try:
            draws = int(data['draws'])
        except (TypeError, ValueError):
            return jsonify({'error': 'draws must be a whole number'}), 400
        if draws < 0 or draws > 20:
            return jsonify({'error': 'draws must be between 0 and 20'}), 400
    if 'weight' in data:
        try:
            weight = float(data['weight'])
        except (TypeError, ValueError):
            return jsonify({'error': 'weight must be a number'}), 400
        if weight < 0 or weight > 1000:
            return jsonify({'error': 'weight must be between 0 and 1000'}), 400

    try:
        with db.get_db() as session:
            row = session.query(BoxType).filter_by(size=size).first()
            if not row:
                return jsonify({'error': 'Box type not found'}), 404

            changed = []
            if draws is not None:
                row.draws = draws
                changed.append(f'draws={draws}')
            if weight is not None:
                row.weight = weight
                changed.append(f'weight={weight}')
            if 'active' in data:
                row.active = bool(data['active'])
                changed.append(f'active={row.active}')
            if 'label' in data:
                row.label = (data['label'] or '').strip() or None
                changed.append('label')

            audit.record(session, current_user['user_id'], 'box_type.update',
                         target=f'box_type:{size}',
                         detail=', '.join(changed) or 'nothing')
            result = row.to_dict()

        box_types.reset_cache()
        return jsonify({'message': 'Box type updated', 'box_type': result}), 200
    except Exception as e:
        logger.error(f"Update box type error: {e}")
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
# Alert channels (Discord webhooks, the staff inbox, ops mail)
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
        # The staff inbox is one destination by definition - it always means
        # "every moderator and admin" - so a second row could only ever produce
        # duplicate notifications.
        if kind == AlertChannel.KIND_INAPP:
            existing_inapp = (session.query(AlertChannel)
                              .filter_by(kind=AlertChannel.KIND_INAPP).first())
            if existing_inapp:
                return None, 'The staff inbox is already set up; edit that one'
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

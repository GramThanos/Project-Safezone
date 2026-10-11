"""The leaderboard of living characters, for players and for staff.

`GET /api/leaderboard` is what players read: public, signed-in only or not at
all, as `leaderboard_visibility` says. It names characters and never the
account behind one. `GET /api/admin/leaderboard` is the staff view - always
available, with each character's owner, its linked account and why a hidden one
is hidden, so the exclusions can be checked against what they hide.
"""
import logging

from flask import Blueprint, jsonify, request
from sqlalchemy import func

from src.database import db
from src.middleware.auth import current_user_optional, moderator_required
from src.models.character import Character
from src.models.user import User
from src.routes.servers import _server_list
from src.utils import leaderboard, settings

logger = logging.getLogger(__name__)
leaderboard_bp = Blueprint('leaderboard', __name__, url_prefix='/api/leaderboard')
leaderboard_admin_bp = Blueprint('leaderboard_admin', __name__,
                                 url_prefix='/api/admin/leaderboard')


def _pick_server(servers):
    """``(server, error_response)`` for the requested server, or the primary."""
    requested = request.args.get('server_id', type=int)
    if requested is not None:
        server = next((s for s in servers if s.get('id') == requested), None)
        if not server:
            return None, (jsonify({'error': 'Server not found'}), 404)
        return server, None
    ordered = sorted(servers, key=lambda s: s.get('id') or 0)
    server = next((s for s in ordered if s.get('is_primary')), None) or \
        (ordered[0] if ordered else None)
    return server, None


def _board(server_id):
    """``(rows, entry, error_response)``: the ranked board with its exclusions."""
    entry, status = leaderboard.fetch(server_id)
    if status != 200:
        return None, None, (jsonify({'error': entry.get('error')}), status)

    characters = entry['characters']
    owners = {(c.get('username') or '').lower() for c in characters} - {''}
    accounts, banned = {}, set()
    if owners:
        with db.get_db() as session:
            linked = (session.query(Character.in_game_username, User)
                      .join(User, User.id == Character.user_id)
                      .filter(Character.server_id == server_id,
                              Character.verified.is_(True),
                              func.lower(Character.in_game_username).in_(owners)))
            for username, user in linked:
                key = username.lower()
                accounts[key] = {'id': user.id, 'username': user.username}
                if user.is_banned():
                    banned.add(key)

    hide_banned = bool(settings.get('leaderboard_hide_banned'))
    rows = leaderboard.rank(characters,
                            excluded=leaderboard.excluded_names(settings.get('leaderboard_excluded')),
                            banned=banned if hide_banned else (),
                            accounts=accounts)
    return rows, entry, None


def _respond(view):
    servers, error, status = _server_list()
    if error:
        return jsonify({'error': error}), status
    server, problem = _pick_server(servers)
    listing = [{'id': s.get('id'), 'name': s.get('name')}
               for s in sorted(servers, key=lambda s: s.get('id') or 0)]
    if problem:
        return problem
    if not server:
        return jsonify({'servers': [], 'server_id': None, 'characters': [],
                        'saved_at': None, 'stale': False}), 200

    rows, entry, problem = _board(server['id'])
    if problem:
        return problem
    return jsonify({'servers': listing, 'server_id': server['id'],
                    'characters': view(rows), 'saved_at': entry.get('saved_at'),
                    'stale': bool(entry.get('stale'))}), 200


@leaderboard_bp.route('', methods=['GET'])
def get_leaderboard():
    """The ranked living characters of one server (`?server_id=`, else the primary)."""
    mode = leaderboard.visibility()
    if mode == leaderboard.DISABLED:
        return jsonify({'error': 'The leaderboard is not available'}), 404
    if mode == leaderboard.AUTHENTICATED and not current_user_optional():
        return jsonify({'error': 'Sign in to see the leaderboard'}), 401
    try:
        return _respond(leaderboard.public_rows)
    except Exception as e:
        logger.error(f'Get leaderboard error: {e}')
        return jsonify({'error': 'Internal server error'}), 500


@leaderboard_admin_bp.route('', methods=['GET'])
@moderator_required
def get_admin_leaderboard(current_user):
    """The whole board for staff, hidden characters included and marked why."""
    try:
        return _respond(lambda rows: rows)
    except Exception as e:
        logger.error(f'Get admin leaderboard error: {e}')
        return jsonify({'error': 'Internal server error'}), 500

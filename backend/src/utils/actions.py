"""Access to the game-server's console action catalog.

The catalog itself (ids, parameters, validation rules) lives in the game-server
service, which is the only place allowed to turn input into a console command.
The backend never re-implements those rules: it asks the game-server to validate
a parameter set (`preview`) and enforces *who* is allowed to run the action on
top of the ``min_role`` the catalog reports.
"""
from src.models.user import User
from src.utils.game_server import gs_request

# Ranked roles used to compare a user against an action's ``min_role``.
ROLE_RANK = {
    User.ROLE_BANNED: 0,
    User.ROLE_PLAYER: 1,
    User.ROLE_MODERATOR: 2,
    User.ROLE_ADMIN: 3,
}


def role_allows(user_role, min_role):
    """Whether ``user_role`` is at least ``min_role``."""
    return ROLE_RANK.get(user_role, 0) >= ROLE_RANK.get(min_role, ROLE_RANK[User.ROLE_ADMIN])


def fetch_catalog(droppable_only=False):
    """Fetch the action catalog. Returns ``(payload, status)``."""
    params = {'droppable': 1} if droppable_only else None
    return gs_request('GET', '/api/actions', params=params)


def validate_action(action_id, params, username=None, droppable_only=False):
    """Validate an action + parameters against the catalog.

    Returns ``(action, command, error, status)``: on success ``error`` is None and
    ``command`` is the console command that would be sent; on failure ``action``
    and ``command`` are None and ``(error, status)`` can be returned to the client.
    """
    if not action_id:
        return None, None, 'action_id is required', 400

    body = {'params': params or {}, 'droppable_only': droppable_only}
    if username:
        body['username'] = username

    resp, status = gs_request('POST', f'/api/actions/{action_id}/preview', json=body)
    if status != 200:
        return None, None, resp.get('error', 'Invalid action'), status

    data = resp.get('data') or {}
    return data.get('action'), data.get('command'), None, 200

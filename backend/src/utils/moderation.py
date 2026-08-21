"""Bridging an account ban to the characters it owns.

The claim flow exists to establish, and prove, that a website account controls a
particular in-game identity. Until now nothing used that link where it matters
most: banning an account locked the website and left the player online.

This closes that. Banning queues a kick and an in-game ban for every verified
character; lifting the ban queues an unban.

**Best effort, and reported as such.** A server that is down must not block the
account ban - locking someone out of the site is the part that has to work, and
it is the part the backend fully controls. The caller gets a per-server outcome
so a moderator can see what actually applied rather than assuming.

Deliberately split in two: `targets()` needs a database session, the sync
functions do network I/O and take plain tuples. Each call to the game-server can
take up to its timeout, and holding a transaction open across several of them
would block writes to the account row for as long as the other service is slow.
"""
import logging

from src.models.character import Character
from src.utils.game_server import gs_request

logger = logging.getLogger(__name__)


def _queue_action(server_id, username, action_id, params=None):
    """Queue one catalog action against a player. Returns (ok, detail).

    `scope: staff` unlocks the moderation half of the catalog; the caller has
    already been gated on the operator's role.
    """
    payload, status = gs_request('POST', '/api/tasks', json={
        'action': 'run_action',
        'server_id': server_id,
        'username': username,
        'kind': 'usable',
        'action_id': action_id,
        'action_params': params or {'username': username},
        'scope': 'staff',
    })
    if status in (200, 201):
        return True, None
    return False, (payload or {}).get('error', f'HTTP {status}')


def targets(session, user_id):
    """``[(server_id, in_game_username)]`` for the account's verified identities.

    Returns plain tuples rather than ORM rows so the caller can close its
    transaction before doing any network I/O.
    """
    rows = (session.query(Character)
            .filter_by(user_id=user_id, verified=True)
            .filter(Character.in_game_username.isnot(None))
            .all())
    return [(c.server_id, c.in_game_username) for c in rows]


def apply_ban(targets_, reason=None):
    """Kick and ban each target. Returns a list of outcome strings."""
    outcomes = []
    for server_id, username in targets_:
        label = f"{username}@server{server_id}"

        # Kick first: a ban alone does not disconnect someone already playing.
        # Allowed to fail - the player may simply be offline, which is the
        # outcome we wanted anyway.
        _queue_action(server_id, username, 'kick',
                      {'username': username, 'reason': reason or 'Account banned'})

        ok, detail = _queue_action(server_id, username, 'ban_user',
                                   {'username': username,
                                    'reason': reason or 'Account banned',
                                    'ban_ip': False})
        outcomes.append(f"banned {label}" if ok else f"FAILED to ban {label}: {detail}")

    return outcomes


def lift_ban(targets_):
    """Unban each target. Returns a list of outcome strings."""
    outcomes = []
    for server_id, username in targets_:
        label = f"{username}@server{server_id}"
        ok, detail = _queue_action(server_id, username, 'unban_user',
                                   {'username': username})
        outcomes.append(f"unbanned {label}" if ok else f"FAILED to unban {label}: {detail}")

    return outcomes

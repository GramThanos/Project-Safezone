#!/usr/bin/env python3
"""Safe builders for server console commands.

These are the command-injection boundary: anything interpolated into a console
command (which is written to the server's stdin) must pass strict validation
here. Usernames are user-influenced; item ids come from the admin catalog but are
still validated defensively.

Every command goes through `build_action_command`, which only accepts actions
declared in `actions.py` with a typed parameter spec. The free-text path that
once existed for pre-catalog rewards has been removed, so there is no longer any
way to reach the console with a string the catalog did not produce.
"""
import actions
from actions import (  # re-exported: callers use commands.* as the boundary API
    CommandError,
    ITEM_ID_RE,
    MAX_COUNT,
    USERNAME_RE,
)

__all__ = [
    'CommandError', 'ITEM_ID_RE', 'MAX_COUNT', 'USERNAME_RE',
    'build_item_command', 'build_action_command',
    'action_requires_online',
]


def _validate_username(username):
    if not username or not USERNAME_RE.match(username):
        raise CommandError('invalid username')


def build_item_command(username, item_id, count=1):
    """Build an `additem` command to give an item to an online player."""
    _validate_username(username)
    if not item_id or not ITEM_ID_RE.match(item_id):
        raise CommandError('invalid item id')
    try:
        count = int(count)
    except (TypeError, ValueError):
        raise CommandError('invalid count')
    if count < 1 or count > MAX_COUNT:
        raise CommandError('count out of range')
    return f'additem "{username}" "{item_id}" {count}'


def build_action_command(username, action_id, params=None, droppable_only=False):
    """Build a command from the whitelisted action catalog.

    ``droppable_only`` rejects staff-only actions, which is what the reward /
    inventory paths pass so a loot drop can never run a moderation command.
    """
    return actions.build(action_id, username, params, droppable_only=droppable_only)


def action_requires_online(action_id):
    """Whether an action is pointless (and so refused) for an offline target."""
    return actions.requires_online(action_id)

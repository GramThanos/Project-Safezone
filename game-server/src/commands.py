#!/usr/bin/env python3
"""Safe builders for server console commands.

These are the command-injection boundary: anything interpolated into a console
command (which is written to the server's stdin) must pass strict validation
here. Usernames are user-influenced; item ids come from the admin catalog but are
still validated defensively.
"""
import re

# PZ in-game usernames: letters, digits, underscore, up to 32 chars.
USERNAME_RE = re.compile(r'^[A-Za-z0-9_]{1,32}$')
# Item ids like "Base.Axe" - letters, digits, underscore, dot.
ITEM_ID_RE = re.compile(r'^[A-Za-z0-9_.]{1,64}$')

MAX_COUNT = 100


class CommandError(Exception):
    """Raised when inputs fail validation and a command cannot be built safely."""


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


def build_usable_command(username, command_template):
    """Build a usable's command from an admin-defined template.

    The template may contain the ``{username}`` placeholder. Newlines/control
    chars are rejected so a single command cannot expand into several.
    """
    _validate_username(username)
    if not command_template or not isinstance(command_template, str):
        raise CommandError('invalid command template')
    if any(ch in command_template for ch in ('\n', '\r', '\x00')):
        raise CommandError('invalid command template')
    return command_template.replace('{username}', username)

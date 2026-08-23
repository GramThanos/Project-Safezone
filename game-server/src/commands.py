#!/usr/bin/env python3
"""Safe builders for server console commands.

These are the command-injection boundary: anything interpolated into a console
command (which is written to the server's stdin) must pass strict validation
here. Usernames are user-influenced; item ids come from the admin catalog but are
still validated defensively.

Catalog actions go through `build_action_command`, which only accepts actions
declared in `actions.py` with a typed parameter spec - that path stays the
whitelist behind staff moderation and server operations.

Reward *usables* take a second path: an admin authors a free-text command
sequence (see `parse_reward_commands`). The text itself is trusted (only an admin
can write a reward), but the one value a player influences - the recipient's
in-game name, substituted for the `{{USERNAME}}` placeholder - is still validated
against `USERNAME_RE` before it reaches the console, and every rendered line is
checked for control characters. `sleep`/`wait` steps are handled by the executor
and never sent to the server.
"""
import re

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
    'parse_reward_commands', 'render_command', 'reward_requires_online',
    'REWARD_MAX_STEPS', 'REWARD_MAX_COMMAND_LEN',
    'SLEEP_MAX_SECONDS', 'SLEEP_TOTAL_MAX_SECONDS',
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


# ---------------------------------------------------------------------------
# Free-text reward command sequences
# ---------------------------------------------------------------------------

# Bounds keep an admin-authored sequence from wedging the single task worker: it
# processes tasks in order, so a reward that slept for minutes or fired hundreds
# of console lines would hold every other delivery behind it.
REWARD_MAX_STEPS = 20            # commands + sleeps, combined
REWARD_MAX_COMMAND_LEN = 500     # per rendered console line
SLEEP_MAX_SECONDS = 30.0         # a single sleep/wait step
SLEEP_TOTAL_MAX_SECONDS = 120.0  # summed across the whole sequence

# The recipient's in-game name goes here. Case-insensitive, with tolerant inner
# spacing, so `{{ username }}` and `{{USERNAME}}` both work.
_PLACEHOLDER_RE = re.compile(r'\{\{\s*username\s*\}\}', re.IGNORECASE)
# A sleep/wait directive: `sleep 5`, `wait 0.5`. Handled by the executor, never
# written to the server.
_SLEEP_RE = re.compile(r'^(?:sleep|wait)\s+(\d+(?:\.\d+)?)$', re.IGNORECASE)


def _has_control_chars(text):
    return any(ch in text for ch in ('\n', '\r', '\x00'))


def _parse_sleep(token):
    """Return the sleep duration for a `sleep`/`wait` token, or None."""
    match = _SLEEP_RE.match(token)
    if not match:
        return None
    seconds = float(match.group(1))
    if seconds <= 0:
        raise CommandError('sleep/wait needs a positive number of seconds')
    if seconds > SLEEP_MAX_SECONDS:
        raise CommandError(f'a single sleep/wait may not exceed {SLEEP_MAX_SECONDS:g} seconds')
    return seconds


def parse_reward_commands(text):
    """Parse an admin-authored reward command block into ordered steps.

    Accepts one command per line; `;` also separates commands on a single line.
    Blank lines and blank segments are ignored. Returns a list of steps, each
    either ``{'type': 'command', 'text': <template>}`` (the `{{USERNAME}}`
    placeholder still unresolved) or ``{'type': 'sleep', 'seconds': <float>}``.

    Raises ``CommandError`` on anything that could not run safely: an empty
    sequence, one with no actual command, too many steps, an over-long line,
    control characters, or an out-of-range sleep. Validation only - nothing here
    touches a live server.
    """
    if not isinstance(text, str):
        raise CommandError('commands must be text')
    if _has_control_chars(text.replace('\n', '')):
        raise CommandError('commands contain control characters')

    steps = []
    total_sleep = 0.0
    has_command = False
    # Split on newlines first, then on `;`, so both styles compose.
    for line in text.splitlines():
        for raw in line.split(';'):
            token = raw.strip()
            if not token:
                continue
            if len(steps) >= REWARD_MAX_STEPS:
                raise CommandError(f'too many steps (limit {REWARD_MAX_STEPS})')

            sleep_seconds = _parse_sleep(token)
            if sleep_seconds is not None:
                total_sleep += sleep_seconds
                if total_sleep > SLEEP_TOTAL_MAX_SECONDS:
                    raise CommandError(
                        f'total sleep/wait may not exceed {SLEEP_TOTAL_MAX_SECONDS:g} seconds')
                steps.append({'type': 'sleep', 'seconds': sleep_seconds})
                continue

            # A leading slash is the in-game chat form; the console wants the
            # bare command, and a stray slash would be silently ignored.
            if token.startswith('/'):
                token = token[1:].lstrip()
                if not token:
                    continue
            if len(token) > REWARD_MAX_COMMAND_LEN:
                raise CommandError(f'a command may not exceed {REWARD_MAX_COMMAND_LEN} characters')
            steps.append({'type': 'command', 'text': token})
            has_command = True

    if not steps:
        raise CommandError('no commands given')
    if not has_command:
        raise CommandError('a reward needs at least one command, not only sleeps')
    return steps


def render_command(template, username=None):
    """Resolve a command template into the exact string sent to the console.

    Substitutes the validated ``username`` for every ``{{USERNAME}}`` placeholder.
    A template that references the placeholder without a valid username is refused
    rather than sent with a hole in it, and the result is re-checked for control
    characters as defence in depth.
    """
    if _PLACEHOLDER_RE.search(template):
        if not username or not USERNAME_RE.match(username):
            raise CommandError('invalid username')
        command = _PLACEHOLDER_RE.sub(username, template)
    else:
        command = template
    if _has_control_chars(command):
        raise CommandError('command contains control characters')
    return command


def reward_requires_online(steps):
    """Whether a parsed sequence targets the recipient (and so needs them online).

    A sequence is player-targeted when any command interpolates ``{{USERNAME}}``;
    otherwise it is server-wide (weather, broadcasts) and runs regardless.
    """
    return any(step['type'] == 'command' and _PLACEHOLDER_RE.search(step['text'])
               for step in steps)

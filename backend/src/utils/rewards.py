"""Validation of free-text reward command sequences.

Like the action catalog, the rules for what a reward command may contain live in
the game-server (the only service allowed to turn text into a console command).
The backend never re-implements them: it asks the game-server to parse and render
a sequence (`preview`) so a bad sequence is rejected at authoring time with the
same rules that will run it at delivery time.
"""
import re

from src.models.reward import Reward
from src.utils.game_server import gs_request

ITEM_ID_RE = re.compile(r'^[A-Za-z0-9_.]{1,64}$')

# `count` reaches an `additem` console command, so it is bounded like any other
# parameter that crosses that boundary rather than trusted from the panel.
MAX_ITEM_COUNT = 1000


def validate_reward_payload(data, partial=False):
    """Validate a reward payload. Returns an error string or None.

    When ``partial`` (PUT), only provided fields are checked. Usables are
    additionally validated against the game-server by the caller (see
    ``validate_usable_commands``). Shared by the reward routes and the box-config
    importer so external configs face the same rules as hand-authored rewards.
    """
    if not partial:
        if not data.get('name'):
            return 'name is required'
        if data.get('kind') not in Reward.KINDS:
            return 'kind must be item or usable'

    if 'count' in data:
        count = data['count']
        if isinstance(count, bool) or not isinstance(count, int):
            return 'count must be a whole number'
        if count < 1 or count > MAX_ITEM_COUNT:
            return f'count must be between 1 and {MAX_ITEM_COUNT}'

    kind = data.get('kind')
    if kind == Reward.KIND_ITEM and 'in_game_id' in data:
        if not data['in_game_id'] or not ITEM_ID_RE.match(data['in_game_id']):
            return 'invalid in_game_id'

    # On create, ensure the kind-specific field is present.
    if not partial:
        if kind == Reward.KIND_ITEM and not data.get('in_game_id'):
            return 'in_game_id is required for items'
        if kind == Reward.KIND_USABLE and not data.get('commands'):
            return 'commands is required for usables'
    return None


def validate_usable_commands(data):
    """Validate a usable's command sequence. Returns ``(error, status)``.

    No-op for item rewards and for legacy catalog usables (no ``commands`` set).
    """
    if data.get('kind') != Reward.KIND_USABLE or not data.get('commands'):
        return None, 200
    _preview, error, status = validate_commands(data['commands'])
    return error, status


def validate_commands(command_text, username=None):
    """Validate a reward command sequence against the game-server.

    Returns ``(preview, error, status)``: on success ``error`` is None and
    ``preview`` is the parsed/rendered result (steps, example console lines,
    whether it needs the recipient online); on failure ``preview`` is None and
    ``(error, status)`` can be returned to the client.
    """
    if not command_text or not str(command_text).strip():
        return None, 'commands is required', 400

    body = {'commands': command_text}
    if username:
        body['username'] = username

    resp, status = gs_request('POST', '/api/rewards/preview', json=body)
    if status != 200:
        return None, resp.get('error', 'Invalid commands'), status
    return resp.get('data') or {}, None, 200

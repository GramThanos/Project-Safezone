#!/usr/bin/env python3
"""Catalog of Project Zomboid admin commands the panel is allowed to run.

Source: https://pzwiki.net/wiki/Admin_commands (stable 42.20.x).

This module is the *whitelist* half of the command-injection boundary: instead of
letting an admin type a raw console command, every runnable action is declared
here with a typed parameter spec and a builder that emits the final command
string. `commands.py` re-exports the builder; nothing else may construct a
console command from user input.

Each action carries:
  id             stable key stored on rewards / sent by the panel
  command        the underlying console command (documentation only)
  label          admin-facing name
  flavor         suggested in-fiction name when used as a loot drop
  description    what it does in game
  category       grouping for the admin UI
  params         list of parameter specs (see PARAM_TYPES)
  droppable      may be attached to a reward players can win and activate
  targets_player the recipient's username is the subject of the command
  requires_online the target must be connected for the command to do anything
  min_role       'moderator' or 'admin'

Commands deliberately NOT exposed
---------------------------------
* Console-context commands - they act on whoever typed them, and we type them on
  the server console where there is no character: `alarm`, `removeitem`,
  `teleport`, `teleportto`, `releasesafehouse`. Note this is why the "teleport
  stone" reward is built on `teleportplayer` (player -> beacon player) rather
  than `teleportto x,y,z`: vanilla has no command that moves *another* player to
  arbitrary coordinates.
* Privilege / credential commands - a panel moderator could escalate to server
  admin with them: `adduser`, `setpassword`, `setaccesslevel`, `addsteamid`,
  `removesteamid`, `removeuserfromwhitelist`, `changeoption` (can rewrite the
  server password), `reloadlua` (arbitrary file name).
* Lifecycle already covered elsewhere: `quit` (use the server stop control).
* WIP / undocumented on the wiki: `addtosafehouse`, `kickfromsafehouse`,
  `createhorde2`, `list`, `remove`, `removezombies` is kept (harmless) but
  `worldgen` is not, `stats` and `log` are console-noise only.
"""
import ipaddress
import re

# PZ in-game usernames: letters, digits, underscore, up to 32 chars.
USERNAME_RE = re.compile(r'^[A-Za-z0-9_]{1,32}$')
# Item / vehicle script ids like "Base.Axe" - letters, digits, underscore, dot.
ITEM_ID_RE = re.compile(r'^[A-Za-z0-9_.]{1,64}$')
# Key ids and perk names.
TOKEN_RE = re.compile(r'^[A-Za-z0-9_]{1,32}$')
STEAM_ID_RE = re.compile(r'^[0-9]{1,20}$')
# Free text (server messages, ban reasons): no quotes, no control characters.
TEXT_RE = re.compile(r'^[^"\r\n\x00\\]{1,200}$')

MAX_COUNT = 100

ROLE_MODERATOR = 'moderator'
ROLE_ADMIN = 'admin'

# Perk names accepted by `addxp` (see PZwiki: Admin commands / Skills).
PERKS = [
    'Aiming', 'Axe', 'Blunt', 'Cooking', 'Doctor', 'Electricity', 'Farming',
    'Fishing', 'Fitness', 'Lightfooted', 'LongBlade', 'Maintenance', 'Mechanics',
    'MetalWelding', 'Nimble', 'PlantScavenging', 'Reloading', 'SmallBlade',
    'SmallBlunt', 'Sneaking', 'Spear', 'Sprinting', 'Strength', 'Tailoring',
    'Trapping', 'Woodwork',
]


class CommandError(Exception):
    """Raised when inputs fail validation and a command cannot be built safely."""


# ---------------------------------------------------------------------------
# Parameter validation
# ---------------------------------------------------------------------------

def _validate_username(username):
    if not username or not isinstance(username, str) or not USERNAME_RE.match(username):
        raise CommandError('invalid username')
    return username


def _v_int(spec, value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise CommandError(f"{spec['name']} must be a whole number")
    low, high = spec.get('min'), spec.get('max')
    if low is not None and value < low:
        raise CommandError(f"{spec['name']} must be at least {low}")
    if high is not None and value > high:
        raise CommandError(f"{spec['name']} must be at most {high}")
    return value


def _v_bool(spec, value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ('true', 'false'):
        return value.lower() == 'true'
    raise CommandError(f"{spec['name']} must be true or false")


def _v_pattern(spec, value, pattern, message):
    if not isinstance(value, str) or not pattern.match(value):
        raise CommandError(f"{spec['name']}: {message}")
    return value


def _v_enum(spec, value):
    if value not in spec.get('options', []):
        raise CommandError(f"{spec['name']} is not one of the allowed values")
    return value


def _v_ip(spec, value):
    try:
        ipaddress.ip_address(str(value))
    except ValueError:
        raise CommandError(f"{spec['name']} must be a valid IP address")
    return str(value)


VALIDATORS = {
    'int': _v_int,
    'bool': _v_bool,
    'enum': _v_enum,
    'ip': _v_ip,
    'username': lambda s, v: _v_pattern(s, v, USERNAME_RE, 'invalid username'),
    'item_id': lambda s, v: _v_pattern(s, v, ITEM_ID_RE, 'invalid item id'),
    'token': lambda s, v: _v_pattern(s, v, TOKEN_RE, 'invalid value'),
    'steam_id': lambda s, v: _v_pattern(s, v, STEAM_ID_RE, 'invalid SteamID'),
    'text': lambda s, v: _v_pattern(s, v, TEXT_RE, 'text may not contain quotes or newlines'),
}
PARAM_TYPES = sorted(VALIDATORS)


def _clean_params(action, params):
    """Validate ``params`` against an action's spec, returning cleaned values.

    Missing optional parameters fall back to their default and are dropped when
    they have none, so builders can test for presence.
    """
    params = params or {}
    if not isinstance(params, dict):
        raise CommandError('parameters must be an object')

    unknown = set(params) - {p['name'] for p in action['params']}
    if unknown:
        raise CommandError(f"unknown parameter(s): {', '.join(sorted(unknown))}")

    cleaned = {}
    for spec in action['params']:
        name = spec['name']
        value = params.get(name)
        if value is None or value == '':
            if spec.get('required'):
                raise CommandError(f"{name} is required")
            if 'default' in spec:
                cleaned[name] = spec['default']
            continue
        cleaned[name] = VALIDATORS[spec['type']](spec, value)
    return cleaned


def _flag(value):
    """Render a boolean as PZ's `-true` / `-false` switch."""
    return '-true' if value else '-false'


# ---------------------------------------------------------------------------
# Builders - one per action, all inputs already validated by _clean_params
# ---------------------------------------------------------------------------

def _b_additem(user, p):
    return f'additem "{user}" "{p["item_id"]}" {p["count"]}'


def _b_addkey(user, p):
    name = p.get('key_name')
    base = f'addkey "{user}" "{p["key_id"]}"'
    return f'{base} "{name}"' if name else base


def _b_addvehicle(user, p):
    return f'addvehicle "{p["script"]}" "{user}"'


def _b_addxp(user, p):
    return f'addxp "{user}" {p["perk"]}={p["amount"]}'


def _b_godmode(user, p):
    return f'godmode "{user}" {_flag(p["enabled"])}'


def _b_invisible(user, p):
    return f'invisible "{user}" {_flag(p["enabled"])}'


def _b_noclip(user, p):
    return f'noclip "{user}" {_flag(p["enabled"])}'


def _b_teleport_to_beacon(user, p):
    return f'teleportplayer "{user}" "{p["destination"]}"'


def _b_createhorde(user, p):
    return f'createhorde {p["count"]} "{user}"'


def _b_lightning(user, p):
    return f'lightning "{user}"'


def _b_thunder(user, p):
    return f'thunder "{user}"'


def _b_chopper(user, p):
    return 'chopper'


def _b_gunshot(user, p):
    return 'gunshot'


def _b_startrain(user, p):
    return f'startrain {p["intensity"]}'


def _b_startstorm(user, p):
    return f'startstorm {p["duration"]}'


def _b_stoprain(user, p):
    return 'stoprain'


def _b_stopweather(user, p):
    return 'stopweather'


def _b_servermsg(user, p):
    return f'servermsg "{p["message"]}"'


def _b_godmodeplayer(user, p):
    return f'godmodeplayer "{p["username"]}" {_flag(p["enabled"])}'


def _b_invisibleplayer(user, p):
    return f'invisibleplayer "{p["username"]}" {_flag(p["enabled"])}'


def _b_teleportplayer(user, p):
    return f'teleportplayer "{p["username"]}" "{p["destination"]}"'


def _b_kick(user, p):
    reason = p.get('reason')
    base = f'kickuser "{p["username"]}"'
    return f'{base} -r "{reason}"' if reason else base


def _b_banuser(user, p):
    parts = [f'banuser "{p["username"]}"']
    if p.get('ban_ip'):
        parts.append('-ip')
    if p.get('reason'):
        parts.append(f'-r "{p["reason"]}"')
    return ' '.join(parts)


def _b_unbanuser(user, p):
    return f'unbanuser "{p["username"]}"'


def _b_banid(user, p):
    return f'banid {p["steam_id"]}'


def _b_unbanid(user, p):
    return f'unbanid {p["steam_id"]}'


def _b_banip(user, p):
    return f'banip {p["ip"]}'


def _b_unbanip(user, p):
    return f'unbanip {p["ip"]}'


def _b_voiceban(user, p):
    return f'voiceban "{p["username"]}" {_flag(p["enabled"])}'


def _b_removemapsymbols(user, p):
    return f'removemapsymbolsforuser "{p["username"]}"'


def _b_removezombies(user, p):
    return 'removezombies'


def _b_save(user, p):
    return 'save'


def _b_players(user, p):
    return 'players'


def _b_showoptions(user, p):
    return 'showoptions'


def _b_reloadoptions(user, p):
    return 'reloadoptions'


def _b_reloadalllua(user, p):
    return 'reloadalllua'


def _b_checkmods(user, p):
    return 'checkModsNeedUpdate'


# ---------------------------------------------------------------------------
# The catalog
# ---------------------------------------------------------------------------

def _action(id, command, label, description, category, build, flavor=None,
            params=None, droppable=False, targets_player=False,
            requires_online=None, min_role=ROLE_ADMIN):
    return {
        'id': id,
        'command': command,
        'label': label,
        'flavor': flavor,
        'description': description,
        'category': category,
        'params': params or [],
        'droppable': droppable,
        'targets_player': targets_player,
        # Player-targeted commands are no-ops when the player is disconnected.
        'requires_online': targets_player if requires_online is None else requires_online,
        'min_role': min_role,
        'build': build,
    }


_CATALOG = [
    # -- Loot: things a player can win and activate on themselves ------------
    _action(
        'give_item', 'additem', 'Give item', 'Places an item straight into the player\'s inventory.',
        'items', _b_additem, flavor='Supply Crate', droppable=True, targets_player=True,
        min_role=ROLE_MODERATOR,
        params=[
            {'name': 'item_id', 'label': 'Item id', 'type': 'item_id', 'required': True,
             'placeholder': 'Base.FirstAidKit', 'help': 'Case sensitive, e.g. Base.Axe'},
            {'name': 'count', 'label': 'Count', 'type': 'int', 'min': 1, 'max': MAX_COUNT, 'default': 1},
        ]),
    _action(
        'give_key', 'addkey', 'Give key', 'Gives the player a named key.',
        'items', _b_addkey, flavor='Safehouse Key', droppable=True, targets_player=True,
        min_role=ROLE_MODERATOR,
        params=[
            {'name': 'key_id', 'label': 'Key id', 'type': 'token', 'required': True, 'placeholder': '7295'},
            {'name': 'key_name', 'label': 'Key name', 'type': 'text', 'placeholder': 'Gift Key'},
        ]),
    _action(
        'spawn_vehicle', 'addvehicle', 'Spawn vehicle at player',
        'Spawns a vehicle next to the player.', 'items', _b_addvehicle,
        flavor='Vehicle Voucher', droppable=True, targets_player=True,
        params=[
            {'name': 'script', 'label': 'Vehicle script', 'type': 'item_id', 'required': True,
             'placeholder': 'Base.VanAmbulance'},
        ]),
    _action(
        'grant_xp', 'addxp', 'Grant XP', 'Awards XP in a single skill.',
        'progression', _b_addxp, flavor='Trainer\'s Tome', droppable=True, targets_player=True,
        min_role=ROLE_MODERATOR,
        params=[
            {'name': 'perk', 'label': 'Skill', 'type': 'enum', 'options': PERKS, 'required': True},
            {'name': 'amount', 'label': 'XP', 'type': 'int', 'min': 1, 'max': 10000, 'default': 100},
        ]),
    _action(
        'god_mode', 'godmode', 'God mode (self)', 'Makes the player invincible until turned off.',
        'buffs', _b_godmode, flavor='Guardian Angel Charm', droppable=True, targets_player=True,
        params=[{'name': 'enabled', 'label': 'Enabled', 'type': 'bool', 'default': True}]),
    _action(
        'invisible', 'invisible', 'Invisible to zombies',
        'Zombies stop noticing the player until turned off.', 'buffs', _b_invisible,
        flavor='Cloak of Shadows', droppable=True, targets_player=True,
        params=[{'name': 'enabled', 'label': 'Enabled', 'type': 'bool', 'default': True}]),
    _action(
        'noclip', 'noclip', 'No-clip', 'Lets the player walk through walls until turned off.',
        'buffs', _b_noclip, flavor='Phase Amulet', droppable=True, targets_player=True,
        params=[{'name': 'enabled', 'label': 'Enabled', 'type': 'bool', 'default': True}]),
    _action(
        'teleport_to_beacon', 'teleportplayer', 'Teleport player to a beacon',
        'Teleports the player to another named player. Park a "beacon" character at '
        'the destination - vanilla has no command that sends another player to raw '
        'x,y,z coordinates.', 'travel', _b_teleport_to_beacon, flavor='Teleport Stone',
        droppable=True, targets_player=True, min_role=ROLE_MODERATOR,
        params=[
            {'name': 'destination', 'label': 'Destination player', 'type': 'username',
             'required': True, 'placeholder': 'BeaconWestPoint'},
        ]),
    _action(
        'summon_horde', 'createhorde', 'Spawn horde near player',
        'Spawns a horde around the player. A curse, not a gift.', 'events', _b_createhorde,
        flavor='Cursed Idol', droppable=True, targets_player=True,
        params=[{'name': 'count', 'label': 'Zombies', 'type': 'int', 'min': 1, 'max': 500, 'default': 30}]),
    _action(
        'lightning', 'lightning', 'Lightning at player', 'Strikes lightning at the player\'s position.',
        'events', _b_lightning, flavor='Storm Rod', droppable=True, targets_player=True,
        min_role=ROLE_MODERATOR),
    _action(
        'thunder', 'thunder', 'Thunder at player', 'Cracks thunder over the player\'s position.',
        'events', _b_thunder, flavor='Thunder Drum', droppable=True, targets_player=True,
        min_role=ROLE_MODERATOR),

    # -- Loot: server-wide flavour (the game picks the target) ---------------
    _action(
        'chopper', 'chopper', 'Helicopter event',
        'Starts the helicopter event over a random player - server-wide, the game '
        'chooses who it follows.', 'events', _b_chopper, flavor='Air Drop Flare',
        droppable=True, requires_online=False),
    _action(
        'gunshot', 'gunshot', 'Gunshot sound',
        'Plays a gunshot near a random player - server-wide.', 'events', _b_gunshot,
        flavor='Decoy Firecracker', droppable=True, requires_online=False,
        min_role=ROLE_MODERATOR),
    _action(
        'start_rain', 'startrain', 'Start rain', 'Starts rain across the server.',
        'weather', _b_startrain, flavor='Rain Totem', droppable=True, requires_online=False,
        params=[{'name': 'intensity', 'label': 'Intensity (1-100)', 'type': 'int',
                 'min': 1, 'max': 100, 'default': 50}]),
    _action(
        'start_storm', 'startstorm', 'Start storm', 'Starts a storm across the server.',
        'weather', _b_startstorm, flavor='Storm Caller', droppable=True, requires_online=False,
        params=[{'name': 'duration', 'label': 'Duration (in-game hours)', 'type': 'int',
                 'min': 1, 'max': 24, 'default': 2}]),
    _action(
        'stop_rain', 'stoprain', 'Stop rain', 'Stops the rain.', 'weather', _b_stoprain,
        flavor='Clear Skies Charm', droppable=True, requires_online=False),
    _action(
        'stop_weather', 'stopweather', 'Stop weather', 'Clears all active weather.',
        'weather', _b_stopweather, flavor='Weather Ward', droppable=True, requires_online=False),
    _action(
        'broadcast', 'servermsg', 'Broadcast message', 'Sends a message to every connected player.',
        'broadcast', _b_servermsg, flavor='Megaphone', droppable=True, requires_online=False,
        min_role=ROLE_MODERATOR,
        params=[{'name': 'message', 'label': 'Message', 'type': 'text', 'required': True,
                 'placeholder': 'Supply drop at West Point!'}]),

    # -- Staff only: applied to a named player, never handed out as loot -----
    _action(
        'god_mode_player', 'godmodeplayer', 'God mode (named player)',
        'Toggles invincibility for any player by name.', 'moderation', _b_godmodeplayer,
        requires_online=True,
        params=[
            {'name': 'username', 'label': 'Player', 'type': 'username', 'required': True},
            {'name': 'enabled', 'label': 'Enabled', 'type': 'bool', 'default': True},
        ]),
    _action(
        'invisible_player', 'invisibleplayer', 'Invisible (named player)',
        'Toggles zombie-invisibility for any player by name.', 'moderation', _b_invisibleplayer,
        requires_online=True,
        params=[
            {'name': 'username', 'label': 'Player', 'type': 'username', 'required': True},
            {'name': 'enabled', 'label': 'Enabled', 'type': 'bool', 'default': True},
        ]),
    _action(
        'teleport_player', 'teleportplayer', 'Teleport one player to another',
        'Moves the first player to the second.', 'moderation', _b_teleportplayer,
        requires_online=True, min_role=ROLE_MODERATOR,
        params=[
            {'name': 'username', 'label': 'Player to move', 'type': 'username', 'required': True},
            {'name': 'destination', 'label': 'Destination player', 'type': 'username', 'required': True},
        ]),
    _action(
        'kick', 'kickuser', 'Kick player', 'Disconnects a player with an optional reason.',
        'moderation', _b_kick, requires_online=True, min_role=ROLE_MODERATOR,
        params=[
            {'name': 'username', 'label': 'Player', 'type': 'username', 'required': True},
            {'name': 'reason', 'label': 'Reason', 'type': 'text'},
        ]),
    _action(
        'ban_user', 'banuser', 'Ban player', 'Bans an account, optionally its IP too.',
        'moderation', _b_banuser, requires_online=False, min_role=ROLE_MODERATOR,
        params=[
            {'name': 'username', 'label': 'Player', 'type': 'username', 'required': True},
            {'name': 'reason', 'label': 'Reason', 'type': 'text'},
            {'name': 'ban_ip', 'label': 'Also ban IP', 'type': 'bool', 'default': False},
        ]),
    _action(
        'unban_user', 'unbanuser', 'Unban player', 'Lifts an account ban.', 'moderation',
        _b_unbanuser, requires_online=False, min_role=ROLE_MODERATOR,
        params=[{'name': 'username', 'label': 'Player', 'type': 'username', 'required': True}]),
    _action(
        'ban_steam_id', 'banid', 'Ban SteamID', 'Bans a SteamID.', 'moderation', _b_banid,
        requires_online=False,
        params=[{'name': 'steam_id', 'label': 'SteamID', 'type': 'steam_id', 'required': True}]),
    _action(
        'unban_steam_id', 'unbanid', 'Unban SteamID', 'Lifts a SteamID ban.', 'moderation',
        _b_unbanid, requires_online=False,
        params=[{'name': 'steam_id', 'label': 'SteamID', 'type': 'steam_id', 'required': True}]),
    _action(
        'ban_ip', 'banip', 'Ban IP', 'Bans an IP address.', 'moderation', _b_banip,
        requires_online=False,
        params=[{'name': 'ip', 'label': 'IP address', 'type': 'ip', 'required': True}]),
    _action(
        'unban_ip', 'unbanip', 'Unban IP', 'Lifts an IP ban.', 'moderation', _b_unbanip,
        requires_online=False,
        params=[{'name': 'ip', 'label': 'IP address', 'type': 'ip', 'required': True}]),
    _action(
        'voice_ban', 'voiceban', 'Voice ban', 'Blocks or restores a player\'s voice chat.',
        'moderation', _b_voiceban, requires_online=False, min_role=ROLE_MODERATOR,
        params=[
            {'name': 'username', 'label': 'Player', 'type': 'username', 'required': True},
            {'name': 'enabled', 'label': 'Muted', 'type': 'bool', 'default': True},
        ]),
    _action(
        'remove_map_symbols', 'removemapsymbolsforuser', 'Clear player map symbols',
        'Removes every map marker a player shared.', 'moderation', _b_removemapsymbols,
        requires_online=False, min_role=ROLE_MODERATOR,
        params=[{'name': 'username', 'label': 'Player', 'type': 'username', 'required': True}]),

    # -- Staff only: server operations ---------------------------------------
    _action(
        'remove_zombies', 'removezombies', 'Remove zombies', 'Clears zombies from the world.',
        'server', _b_removezombies, requires_online=False),
    _action(
        'save_world', 'save', 'Save world', 'Writes the world to disk.', 'server', _b_save,
        requires_online=False),
    _action(
        'list_players', 'players', 'List connected players', 'Prints the connected players to the log.',
        'server', _b_players, requires_online=False, min_role=ROLE_MODERATOR),
    _action(
        'show_options', 'showoptions', 'Show server options', 'Prints current server options to the log.',
        'server', _b_showoptions, requires_online=False),
    _action(
        'reload_options', 'reloadoptions', 'Reload server options',
        'Re-reads ServerOptions.ini and pushes it to clients.', 'server', _b_reloadoptions,
        requires_online=False),
    _action(
        'reload_lua', 'reloadalllua', 'Reload all Lua', 'Reloads every server Lua script.',
        'server', _b_reloadalllua, requires_online=False),
    _action(
        'check_mods', 'checkModsNeedUpdate', 'Check mods for updates',
        'Writes to the log whether any mod has an update.', 'server', _b_checkmods,
        requires_online=False),
]

ACTIONS = {a['id']: a for a in _CATALOG}

CATEGORIES = [
    ('items', 'Items & gear'),
    ('progression', 'Skills'),
    ('buffs', 'Buffs'),
    ('travel', 'Travel'),
    ('events', 'World events'),
    ('weather', 'Weather'),
    ('broadcast', 'Broadcast'),
    ('moderation', 'Moderation'),
    ('server', 'Server operations'),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get(action_id):
    """Return the raw catalog entry, or None."""
    return ACTIONS.get(action_id)


def _template(action):
    """A ready-to-edit console line for this action, for the reward editor.

    The builders are pure formatters, so feeding them placeholder tokens yields
    the exact command shape with ``{{USERNAME}}`` where the recipient goes and
    ``{param}`` for each parameter - authoritative and drift-free, since it comes
    from the same builder that runs the real command. Optional parts are shown so
    the admin can see them and delete what they do not want.
    """
    params = {p['name']: '{' + p['name'] + '}' for p in action['params']}
    try:
        return action['build']('{{USERNAME}}', params)
    except Exception:
        return action['command']


def to_public(action):
    """Strip the builder so the entry can be serialised to JSON, adding a template."""
    public = {k: v for k, v in action.items() if k != 'build'}
    public['template'] = _template(action)
    return public


def catalog(droppable_only=False):
    """Serialisable catalog, optionally limited to loot-safe actions."""
    return [to_public(a) for a in _CATALOG if a['droppable'] or not droppable_only]


def requires_online(action_id):
    """Whether delivery should be refused when the target is offline."""
    action = ACTIONS.get(action_id)
    return True if action is None else action['requires_online']


def build(action_id, username, params=None, droppable_only=False):
    """Build the console command for ``action_id``.

    ``username`` is the reward recipient; it is only interpolated for actions
    that target a player, but it is still validated whenever it is supplied so a
    malformed name can never reach the console.
    """
    action = ACTIONS.get(action_id)
    if action is None:
        raise CommandError('unknown action')
    if droppable_only and not action['droppable']:
        raise CommandError('this action cannot be used as a player reward')

    if action['targets_player'] or username:
        username = _validate_username(username)

    command = action['build'](username, _clean_params(action, params))
    # Defence in depth: a builder must never emit a multi-line command.
    if any(ch in command for ch in ('\n', '\r', '\x00')):
        raise CommandError('command contains control characters')
    return command

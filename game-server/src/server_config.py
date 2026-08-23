#!/usr/bin/env python3
"""Reading and writing a server's Project Zomboid INI.

**Assumption to verify on a real install.** Project Zomboid keeps a dedicated
server's configuration at ``$ZOMBOID_DATA_DIR/Server/<server name>.ini``, in a
flat ``key=value`` format with ``#`` comments. Both the directory and the file
name pattern are derived from configuration rather than hardcoded, so if this is
wrong on your install it is one setting to change, not a rewrite.

Why a whitelist rather than a free-text editor
----------------------------------------------
The same reasoning as the console action catalog: an arbitrary INI editor is a
way to write arbitrary content into a file the server executes decisions from,
and `RCONPassword` sitting in the same file as `PublicName` means a careless
"edit everything" screen leaks credentials into a browser. Only declared keys
are readable and writable, and the ones that are credentials are declared
write-only.

Unknown keys already in the file are **preserved untouched** on write. Rewriting
a config by serialising only what we understand is how you silently delete
somebody's careful tuning.
"""
import os
import re

import config

# key -> (type, help). `secret` keys are never returned, only reported as set.
#   bool  -> true/false
#   int   -> whole number
#   text  -> single line, no newlines
SETTINGS = {
    'PublicName': ('text', 'Name shown in the server browser'),
    'PublicDescription': ('text', 'Description shown in the server browser'),
    'Public': ('bool', 'List this server publicly'),
    'MaxPlayers': ('int', 'Maximum simultaneous players'),
    'PauseEmpty': ('bool', 'Pause the world when nobody is connected'),
    'PVP': ('bool', 'Allow players to damage each other'),
    'Open': ('bool', 'Allow anyone to join without being whitelisted'),
    'ServerWelcomeMessage': ('text', 'Shown to a player when they connect'),
    'SafetySystem': ('bool', 'PVP safety toggle'),
    'DisplayUserName': ('bool', 'Show usernames above characters'),
    'MinutesPerPage': ('int', 'Reading speed, minutes per page'),
    'SaveWorldEveryMinutes': ('int', 'How often the world is written to disk'),
    'GlobalChat': ('bool', 'Enable global chat'),
    'AnnounceDeath': ('bool', 'Announce player deaths'),
    # There is no router to ask inside a container, and the discovery attempt is
    # made during boot - the game prints "If the server hangs here, set
    # UPnP=false" immediately before it. Ports are published by Docker, so this
    # has nothing to do even when it works.
    'UPnP': ('bool', 'Ask the router to forward ports. Leave off in Docker: '
                     'ports are published by the container, and the discovery '
                     'can stall the boot'),
    'Mods': ('text', 'Semicolon-separated mod ids'),
    'WorkshopItems': ('text', 'Semicolon-separated Workshop ids'),
    'Password': ('secret', 'Server join password'),
    'RCONPassword': ('secret', 'RCON password'),
}

LINE_RE = re.compile(r'^\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*$')


def path_for(server_name):
    """The INI path for a server, or None if the name is unusable."""
    import logs  # shared name validation
    if not logs.is_safe_name(server_name):
        return None
    return os.path.join(config.ZOMBOID_DATA_DIR, 'Server', f'{server_name}.ini')


def _coerce_out(kind, raw):
    """INI text -> a JSON-friendly value."""
    if kind == 'bool':
        return str(raw).strip().lower() == 'true'
    if kind == 'int':
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return None
    return raw


def _coerce_in(kind, value):
    """A submitted value -> INI text, or raise ValueError."""
    if kind == 'bool':
        return 'true' if value in (True, 'true', 'True', 1, '1') else 'false'
    if kind == 'int':
        try:
            return str(int(value))
        except (TypeError, ValueError):
            raise ValueError('must be a whole number')
    text = '' if value is None else str(value)
    if any(ch in text for ch in ('\n', '\r')):
        # A newline would let one setting become two.
        raise ValueError('must be a single line')
    return text


def read(server_name):
    """Declared settings for a server. Returns ``(settings, error)``."""
    path = path_for(server_name)
    if not path:
        return None, 'That server name cannot be used to locate a config file'
    if not os.path.isfile(path):
        return None, f'No config at {path} - has this server ever started?'

    present = {}
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            for line in handle:
                if line.lstrip().startswith('#'):
                    continue
                match = LINE_RE.match(line)
                if match:
                    present[match.group(1)] = match.group(2)
    except OSError as e:
        return None, f'Could not read the config: {e}'

    out = []
    for key, (kind, help_text) in SETTINGS.items():
        entry = {'key': key, 'type': kind, 'help': help_text}
        raw = present.get(key)
        if kind == 'secret':
            entry['is_set'] = bool(raw)
        else:
            entry['value'] = _coerce_out(kind, raw) if raw is not None else None
        out.append(entry)
    return out, None


def write(server_name, values):
    """Update declared settings in place. Returns ``(changed_keys, error)``.

    Rewrites only the lines it understands and appends genuinely new keys.
    Everything else in the file is carried through byte for byte - a server
    config holds a lot of careful tuning that this module has no opinion about.
    """
    path = path_for(server_name)
    if not path:
        return None, 'That server name cannot be used to locate a config file'
    if not os.path.isfile(path):
        return None, f'No config at {path} - has this server ever started?'

    prepared = {}
    for key, value in (values or {}).items():
        spec = SETTINGS.get(key)
        if not spec:
            return None, f'{key} is not an editable setting'
        kind = spec[0]
        try:
            prepared[key] = _coerce_in('text' if kind == 'secret' else kind, value)
        except ValueError as e:
            return None, f'{key} {e}'

    if not prepared:
        return [], None

    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            lines = handle.readlines()
    except OSError as e:
        return None, f'Could not read the config: {e}'

    changed = []
    seen = set()
    for index, line in enumerate(lines):
        if line.lstrip().startswith('#'):
            continue
        match = LINE_RE.match(line)
        if not match:
            continue
        key = match.group(1)
        if key in prepared:
            seen.add(key)
            if match.group(2) != prepared[key]:
                lines[index] = f'{key}={prepared[key]}\n'
                changed.append(key)

    for key, value in prepared.items():
        if key not in seen:
            if lines and not lines[-1].endswith('\n'):
                lines[-1] += '\n'
            lines.append(f'{key}={value}\n')
            changed.append(key)

    try:
        # Write beside the original and swap: a config truncated by a failed
        # write is a server that will not start.
        temporary = path + '.new'
        with open(temporary, 'w', encoding='utf-8') as handle:
            handle.writelines(lines)
        os.replace(temporary, path)
    except OSError as e:
        return None, f'Could not write the config: {e}'

    return changed, None


# ---------------------------------------------------------------------------
# Raw editing: every key in the file, not just the declared ones
# ---------------------------------------------------------------------------
#
# The whitelist above is the everyday screen - typed, validated, safe. This is
# the advanced one: it shows whatever is actually in the file, including keys
# this code has never heard of, and lets a key be *disabled* by commenting it
# out rather than deleted.
#
# Commenting is not the same as blanking. `#MaxPlayers=16` means "use whatever
# the game defaults to"; `MaxPlayers=` means "the empty string", which for a
# numeric option is how you get a server that will not boot. Disabling keeps the
# old value in the comment so re-enabling restores it.
#
# One ambiguity is inherent and worth knowing about: a documentation comment
# that happens to read `# MaxPlayers=16` is indistinguishable from a key
# somebody disabled. It will appear as a disabled key. Re-enabling it just sets
# a value that was probably already the default, so the blast radius is small.

import shutil

# The game rewrites this file when it shuts down, so anything written while it
# runs is lost. `sleeping` counts as off - the process genuinely is not running -
# but a wake can start it, which is why the state is re-checked immediately
# before the write rather than only when the form was opened.
EDITABLE_STATES = {'stopped', 'failed', 'sleeping'}

SECRET_KEYS = {key for key, (kind, _) in SETTINGS.items() if kind == 'secret'}

# Matches an enabled or commented-out `key = value` line. A comment without an
# `=` (a real comment) does not match, which is what keeps prose out of the
# editor.
RAW_LINE_RE = re.compile(r'^(\s*)(#\s*)?([A-Za-z0-9_]+)\s*=\s*(.*?)\s*$')

NEW_KEY_RE = re.compile(r'^[A-Za-z0-9_]{1,64}$')


def _version(path):
    """A token identifying this revision of the file.

    Used as an optimistic lock: two admins with the form open should not be able
    to silently overwrite each other, and mtime is enough to notice.
    """
    try:
        stat = os.stat(path)
        return f'{int(stat.st_mtime)}-{stat.st_size}'
    except OSError:
        return None


def read_raw(server_name):
    """Every key in a server's INI. Returns ``(payload, error)``.

    Secrets are reported as set or not, never returned - the same rule as the
    whitelist view. Nothing is gained by putting an RCON password in a browser.
    """
    path = path_for(server_name)
    if not path:
        return None, 'That server name cannot be used to locate a config file'
    if not os.path.isfile(path):
        return None, (f'No config at {path}. Project Zomboid writes it on first '
                      f'launch, so start the server once before editing it.')

    entries = []
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            for number, line in enumerate(handle, start=1):
                match = RAW_LINE_RE.match(line.rstrip('\n'))
                if not match:
                    continue
                _, comment, key, value = match.groups()
                declared = SETTINGS.get(key)
                secret = key in SECRET_KEYS
                entries.append({
                    'key': key,
                    'value': None if secret else value,
                    'is_set': bool(value) if secret else None,
                    'disabled': bool(comment),
                    'secret': secret,
                    'line': number,
                    # Declared keys keep their type and help, so the advanced
                    # view is not strictly worse than the simple one.
                    'type': declared[0] if declared else None,
                    'help': declared[1] if declared else None,
                })
    except OSError as e:
        return None, f'Could not read the config: {e}'

    return {'entries': entries, 'version': _version(path), 'path': path}, None


def _validate_raw_changes(changes):
    """Check a raw edit payload. Returns an error string, or None."""
    if not isinstance(changes, dict) or not changes:
        return 'Nothing to change'

    for key, change in changes.items():
        if not NEW_KEY_RE.match(str(key)):
            return f"'{key}' is not a valid setting name"
        if not isinstance(change, dict):
            return f"'{key}' must be an object with value and disabled"
        text = '' if change.get('value') is None else str(change['value'])
        if any(ch in text for ch in ('\n', '\r')):
            # A newline would turn one setting into two.
            return f"'{key}' must be a single line"
    return None


def write_raw(server_name, changes, expected_version=None):
    """Apply raw edits. Returns ``(result, error)``.

    ``changes`` is ``{key: {"value": str, "disabled": bool}}``. A missing key is
    left alone; a key not already in the file is appended.

    Lines that are not recognised as settings - comments, blanks, anything this
    code does not understand - are carried through untouched.
    """
    path = path_for(server_name)
    if not path:
        return None, 'That server name cannot be used to locate a config file'
    if not os.path.isfile(path):
        return None, f'No config at {path} - start the server once first'

    error = _validate_raw_changes(changes)
    if error:
        return None, error

    if expected_version:
        current = _version(path)
        if current and current != expected_version:
            return None, ('Somebody else changed this file since you opened it. '
                          'Reload before saving so their edits are not lost.')

    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            lines = handle.readlines()
    except OSError as e:
        return None, f'Could not read the config: {e}'

    # Existing values, so a blank secret can mean "leave it alone".
    existing = {}
    for line in lines:
        match = RAW_LINE_RE.match(line.rstrip('\n'))
        if match:
            existing.setdefault(match.group(3), match.group(4))

    def render(key, change):
        value = change.get('value')
        if key in SECRET_KEYS and (value is None or value == ''):
            value = existing.get(key, '')      # untouched secret keeps its value
        value = '' if value is None else str(value)
        prefix = '#' if change.get('disabled') else ''
        return f'{prefix}{key}={value}\n'

    applied, seen = [], set()
    for index, line in enumerate(lines):
        match = RAW_LINE_RE.match(line.rstrip('\n'))
        if not match:
            continue
        key = match.group(3)
        if key not in changes or key in seen:
            continue
        seen.add(key)
        replacement = render(key, changes[key])
        if replacement != line:
            lines[index] = replacement
            applied.append(key)

    for key, change in changes.items():
        if key not in seen:
            if lines and not lines[-1].endswith('\n'):
                lines[-1] += '\n'
            lines.append(render(key, change))
            applied.append(key)

    try:
        # A copy before every write. A config this tool corrupts is a server
        # that will not start, and the previous version is worth one file.
        shutil.copy2(path, path + '.bak')
        temporary = path + '.new'
        with open(temporary, 'w', encoding='utf-8') as handle:
            handle.writelines(lines)
        os.replace(temporary, path)
    except OSError as e:
        return None, f'Could not write the config: {e}'

    return {'changed': applied, 'version': _version(path)}, None


# ---------------------------------------------------------------------------
# Portable templates: a shareable subset of a server's config
# ---------------------------------------------------------------------------
#
# A template is a curated INI - gameplay tuning, mod lists, welcome messages -
# that can be exported from one server, published to the community repo, and
# imported onto another. Unlike the whitelist editor above it is deliberately
# open: any INI key may be carried, so the feature keeps working as Project
# Zomboid adds settings this code has never enumerated.
#
# What keeps that safe is a *blacklist* rather than a whitelist. Three kinds of
# key are never exported into a template and never applied from one, however the
# template was authored:
#
#   * credentials - `Password`, `RCONPassword`. A template is shared; these are
#     not. Matched by the `Password` suffix so a future credential key is caught
#     without a code change.
#   * network ports - `DefaultPort`, `UDPPort`, `SteamPort1/2`, `RCONPort`, and
#     anything else ending in `Port`. This stack assigns ports in the `servers`
#     table and publishes them through Docker; the game must not be handed a
#     different one in its INI. Excluding them here is also why a template needs
#     no per-value variable substitution - there is no machine-specific value
#     left in it to substitute.
#   * per-server identity - `PublicName` / `PublicDescription` (this operator's,
#     not the author's) and `ResetID` / `ServerPlayerID` (per-world ids; changing
#     them forces connected clients to wipe and redownload the world).
#
# The suffix rules are the version-proof half: a port or credential key added in
# a later PZ build is excluded the day it appears, with no list to update.
TEMPLATE_EXCLUDED_KEYS = {
    'PublicName', 'PublicDescription',
    'ResetID', 'ServerPlayerID',
    # Steam's ports end in a digit, so the `Port` suffix below does not catch
    # them - they are named explicitly.
    'SteamPort1', 'SteamPort2',
}
TEMPLATE_EXCLUDED_SUFFIXES = ('Port', 'Password')

# One paste's worth of settings. A real PZ INI has well over a hundred keys, so
# this is a bound against a hostile file, not a limit a genuine template hits.
MAX_TEMPLATE_SETTINGS = 500


def is_template_excluded(key):
    """Whether a key may never travel in a template (see TEMPLATE_EXCLUDED_KEYS)."""
    return key in TEMPLATE_EXCLUDED_KEYS or key.endswith(TEMPLATE_EXCLUDED_SUFFIXES)


def export_template(server_name, name='', description=''):
    """Build a portable template from a server's current config.

    Returns ``(payload, error)``. Only *enabled* keys are exported (a disabled
    key means "use the game default", which is what an absent key means in a
    template too), and blacklisted keys are dropped. The result is the same
    ``server-template/v1`` shape the importer accepts.
    """
    path = path_for(server_name)
    if not path:
        return None, 'That server name cannot be used to locate a config file'
    if not os.path.isfile(path):
        return None, (f'No config at {path}. Project Zomboid writes it on first '
                      f'launch, so start the server once before exporting it.')

    settings = {}
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            for line in handle:
                match = RAW_LINE_RE.match(line.rstrip('\n'))
                if not match:
                    continue
                _, comment, key, value = match.groups()
                if comment:                       # disabled key: skip, as above
                    continue
                if is_template_excluded(key):
                    continue
                settings[key] = value
    except OSError as e:
        return None, f'Could not read the config: {e}'

    return {
        'schema': 'safezone.server-template/v1',
        'name': (name or '').strip() or f'{server_name} config',
        'description': (description or '').strip(),
        'settings': settings,
    }, None


def import_template(server_name, settings, expected_version=None):
    """Apply a template's settings to a server's INI. Returns ``(result, error)``.

    Blacklisted keys are silently filtered and reported under ``skipped`` rather
    than failing the whole import - a template that happens to carry a port is
    applied minus the port, not rejected. Everything that survives the filter is
    written through the same safe, backed-up path as a raw edit, so unknown keys
    already in the file are preserved and the optimistic version lock still holds.
    """
    if not isinstance(settings, dict) or not settings:
        return None, 'The template has no settings'
    if len(settings) > MAX_TEMPLATE_SETTINGS:
        return None, f'A template may hold at most {MAX_TEMPLATE_SETTINGS} settings'

    changes = {}
    skipped = []
    for key, value in settings.items():
        if is_template_excluded(key):
            skipped.append(key)
            continue
        changes[key] = {'value': '' if value is None else str(value), 'disabled': False}

    if not changes:
        return None, 'The template has no applicable settings (all were excluded)'

    result, error = write_raw(server_name, changes, expected_version)
    if error:
        return None, error

    result['skipped'] = skipped
    return result, None

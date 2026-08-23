#!/usr/bin/env python3
"""Reading and writing a server's Project Zomboid SandboxVars.

The *gameplay* half of a server's configuration. The `.ini` handled by
:mod:`server_config` holds non-gameplay settings (ports, PvP, safehouse rules);
the difficulty knobs an operator actually reaches for - whether water and power
ever cut, how much loot spawns, how many zombies, how fast hunger and thirst
climb - live in a separate Lua file:

    $ZOMBOID_DATA_DIR/Server/<server name>_SandboxVars.lua

That file is Lua, not INI, but it is only ever a single table literal:

    SandboxVars = {
        VERSION = 6,
        Zombies = 4,            -- 6 = None ... 1 = Insane
        WaterShut = 9,          -- 9 = Disabled
        ElecShut = 9,
        FoodLootNew = 1.6,
        StatsDecrease = 5,      -- 5 = Very Slow
        WorldItemRemovalList = "Base.Hat, Base.Glasses",
        ZombieLore = {          -- nested groups exist and are left untouched
            Speed = 2,
        },
    }

Why this is not a general Lua editor
------------------------------------
The file is executed by the game, so writing arbitrary Lua into it is the same
class of risk as the INI editor guarded against. This module therefore only ever
reads and rewrites **top-level scalar** assignments (number, boolean, quoted
string). Nested tables, comments, and anything it does not recognise are
preserved byte for byte - the same "rewrite only what we understand, keep the
rest" contract as :mod:`server_config`. A value is only ever emitted through
:func:`_render_value`, which can produce a number, ``true``/``false`` or a quoted
string and nothing else, so a template can never inject code.

Depth tracking
--------------
Telling a top-level key (``Zombies``) from one nested inside a group
(``ZombieLore.Speed``) is done by counting braces, string-aware and
comment-aware, so a ``{`` inside a string or a ``--`` comment does not throw the
count off. Only assignments seen at depth 1 (directly inside ``SandboxVars = {``)
are eligible.
"""
import os
import re

import config

# Never carried in a template. VERSION is the sandbox schema revision, tied to
# the game build that wrote the file; a template author's copy must not overwrite
# the one this server was generated with, or the game may reject or migrate it.
SANDBOX_EXCLUDED_KEYS = {'VERSION'}

# One paste's worth of keys. A real sandbox file has a few hundred; this bounds a
# hostile import, not a genuine one.
MAX_SANDBOX_SETTINGS = 1000

_ASSIGN_RE = re.compile(r'^(\s*)([A-Za-z0-9_]+)\s*=\s*')


def path_for(server_name):
    """The SandboxVars path for a server, or None if the name is unusable."""
    import logs  # shared name validation
    if not logs.is_safe_name(server_name):
        return None
    return os.path.join(config.ZOMBOID_DATA_DIR, 'Server', f'{server_name}_SandboxVars.lua')


def _version(path):
    """A token identifying this revision of the file (mtime + size)."""
    try:
        stat = os.stat(path)
        return f'{int(stat.st_mtime)}-{stat.st_size}'
    except OSError:
        return None


def _line_start_depths(text):
    """Brace depth at the start of each line, string- and comment-aware.

    Returns a list one longer than the number of lines, so ``depths[i]`` is the
    depth entering line ``i``. A ``{``/``}`` inside a ``"..."`` / ``'...'`` string
    or after a ``--`` line comment is ignored, which is what lets a value like
    ``"a, b"`` or a commented-out brace sit in the file without corrupting the
    count.
    """
    depths = [0]
    depth = 0
    in_str = False
    str_ch = ''
    esc = False
    in_comment = False
    prev = ''
    for ch in text:
        if ch == '\n':
            depths.append(depth)
            in_comment = False
            in_str = False        # sandbox scalars are single-line; reset defensively
            esc = False
            prev = ''
            continue
        if in_comment:
            prev = ch
            continue
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == str_ch:
                in_str = False
            prev = ch
            continue
        if ch == '-' and prev == '-':
            in_comment = True
            prev = ch
            continue
        if ch in ('"', "'"):
            in_str = True
            str_ch = ch
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
        prev = ch
    return depths


def _read_value_raw(s):
    """The raw text of the scalar value at the start of ``s`` (after ``key =``).

    Stops at the end of a quoted string, or at the first comma/whitespace for a
    bare number or boolean - so a comma inside a string is not mistaken for the
    end of the value.
    """
    if not s:
        return ''
    if s[0] in ('"', "'"):
        quote = s[0]
        i = 1
        esc = False
        while i < len(s):
            c = s[i]
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == quote:
                return s[:i + 1]
            i += 1
        return s[:i]              # unterminated; take what there is
    match = re.match(r'[^,\s]+', s)
    return match.group(0) if match else ''


def _typed(raw):
    """A raw Lua scalar as ``(python_value, kind)``.

    ``kind`` is one of ``bool``/``int``/``float``/``string``, or ``None`` when the
    value is something this module does not model (left visible but not editable).
    """
    if raw in ('true', 'false'):
        return raw == 'true', 'bool'
    if re.match(r'^-?\d+$', raw):
        return int(raw), 'int'
    if re.match(r'^-?\d+\.\d+$', raw):
        return float(raw), 'float'
    if len(raw) >= 2 and raw[0] in ('"', "'") and raw[-1] == raw[0]:
        inner = raw[1:-1].replace('\\"', '"').replace("\\'", "'").replace('\\\\', '\\')
        return inner, 'string'
    return raw, None


def _render_value(value):
    """A Python value as Lua source text. Raises ValueError on a bad string.

    The only shapes it can emit are a number, ``true``/``false`` and a
    double-quoted string - the whole reason a template cannot smuggle code in.
    """
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    text = '' if value is None else str(value)
    if any(ch in text for ch in ('\n', '\r')):
        raise ValueError('must be a single line')
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _scan(text):
    """Parse a SandboxVars file. Returns ``(entries, outer_close_index, indent)``.

    ``entries`` maps each top-level scalar key to
    ``{'value', 'type', 'line', 'value_start', 'value_raw'}`` - enough to type the
    value for a reader and to overwrite exactly that span for a writer.
    ``outer_close_index`` is the line holding the ``}`` that closes the table
    (where new keys are inserted before), or None if the file is not shaped as
    expected. ``indent`` is the indentation to give a newly-added key.
    """
    lines = text.splitlines(keepends=True)
    depths = _line_start_depths(text)
    entries = {}
    indent = '    '
    outer_close_index = None

    for i, line in enumerate(lines):
        depth = depths[i] if i < len(depths) else 0
        if depth == 1 and outer_close_index is None:
            # The line that takes us from inside the table back out closes it.
            if i + 1 < len(depths) and depths[i + 1] == 0 and '}' in line:
                outer_close_index = i
        if depth != 1:
            continue
        match = _ASSIGN_RE.match(line)
        if not match:
            continue
        after = line[match.end():]
        if after.startswith('{'):
            continue                     # a nested group opens here; not a scalar
        key = match.group(2)
        value_start = match.end()
        raw = _read_value_raw(after)
        value, kind = _typed(raw)
        indent = match.group(1) or indent
        entries[key] = {
            'value': value,
            'type': kind,
            'line': i,
            'value_start': value_start,
            'value_raw': raw,
        }

    return entries, outer_close_index, indent


def read(server_name):
    """Top-level sandbox settings for a server. Returns ``(payload, error)``.

    ``payload`` is ``{entries, version, path}`` where each entry is
    ``{key, value, type}`` (VERSION is reported like any other, so the panel can
    show it, but it is refused on write - see :func:`write`).
    """
    path = path_for(server_name)
    if not path:
        return None, 'That server name cannot be used to locate a sandbox file'
    if not os.path.isfile(path):
        return None, (f'No sandbox file at {path}. Project Zomboid writes it on '
                      f'first launch, so start the server once before editing it.')

    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            text = handle.read()
    except OSError as e:
        return None, f'Could not read the sandbox file: {e}'

    entries, _close, _indent = _scan(text)
    out = [{'key': key, 'value': e['value'], 'type': e['type']}
           for key, e in entries.items()]
    return {'entries': out, 'version': _version(path), 'path': path}, None


def _validate_changes(changes):
    """Check a write payload. Returns an error string, or None."""
    if not isinstance(changes, dict) or not changes:
        return 'Nothing to change'
    if len(changes) > MAX_SANDBOX_SETTINGS:
        return f'A sandbox change may touch at most {MAX_SANDBOX_SETTINGS} settings'
    for key, value in changes.items():
        if not re.match(r'^[A-Za-z0-9_]{1,64}$', str(key)):
            return f"'{key}' is not a valid sandbox key"
        if not isinstance(value, (bool, int, float, str)) and value is not None:
            return f"'{key}' must be a number, boolean or string"
    return None


def write(server_name, changes, expected_version=None):
    """Update top-level scalar sandbox keys in place. Returns ``(result, error)``.

    Only keys that already exist as top-level scalars are rewritten; a key not in
    the file is appended just inside the table. Nested groups, comments and
    unrecognised lines are carried through untouched, and only the value span of a
    changed line is replaced, so its indentation and trailing comment survive.
    """
    path = path_for(server_name)
    if not path:
        return None, 'That server name cannot be used to locate a sandbox file'
    if not os.path.isfile(path):
        return None, f'No sandbox file at {path} - start the server once first'

    error = _validate_changes(changes)
    if error:
        return None, error

    if expected_version:
        current = _version(path)
        if current and current != expected_version:
            return None, ('Somebody else changed this file since you opened it. '
                          'Reload before saving so their edits are not lost.')

    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            text = handle.read()
    except OSError as e:
        return None, f'Could not read the sandbox file: {e}'

    entries, outer_close_index, indent = _scan(text)
    lines = text.splitlines(keepends=True)

    # Render every value first, so a bad string fails before anything is written.
    rendered = {}
    for key, value in changes.items():
        try:
            rendered[key] = _render_value(value)
        except ValueError as e:
            return None, f'{key} {e}'

    changed = []
    additions = {}
    for key, value_text in rendered.items():
        entry = entries.get(key)
        if entry is None:
            additions[key] = value_text
            continue
        line = lines[entry['line']]
        start = entry['value_start']
        end = start + len(entry['value_raw'])
        if line[start:end] == value_text:
            continue                     # already this value
        lines[entry['line']] = line[:start] + value_text + line[end:]
        changed.append(key)

    if additions:
        if outer_close_index is None:
            return None, ('The sandbox file is not shaped as expected (no closing '
                          'brace found); refusing to add new keys to it')
        new_lines = [f'{indent}{key} = {text},\n' for key, text in additions.items()]
        # Guard the line above the closing brace against a missing newline.
        if outer_close_index > 0 and not lines[outer_close_index - 1].endswith('\n'):
            lines[outer_close_index - 1] += '\n'
        lines[outer_close_index:outer_close_index] = new_lines
        changed.extend(additions)

    if not changed:
        return {'changed': [], 'version': _version(path)}, None

    try:
        # Copy then swap, as the INI writer does: a sandbox file this tool
        # corrupts is a server that will not start, and the previous version is
        # worth one file.
        import shutil
        shutil.copy2(path, path + '.bak')
        temporary = path + '.new'
        with open(temporary, 'w', encoding='utf-8') as handle:
            handle.writelines(lines)
        os.replace(temporary, path)
    except OSError as e:
        return None, f'Could not write the sandbox file: {e}'

    return {'changed': changed, 'version': _version(path)}, None


# ---------------------------------------------------------------------------
# Portable templates
# ---------------------------------------------------------------------------

def is_template_excluded(key):
    """Whether a sandbox key may never travel in a template (see the constant)."""
    return key in SANDBOX_EXCLUDED_KEYS


def export_template(server_name, name='', description=''):
    """Build a portable world template from a server's sandbox. ``(payload, err)``.

    Every top-level scalar is carried except the blacklist (VERSION). Nested
    groups are not exported - the template is the everyday difficulty dials, not
    a whole-file clone.
    """
    payload, error = read(server_name)
    if error:
        return None, error

    sandbox = {}
    for entry in payload['entries']:
        key = entry['key']
        if is_template_excluded(key) or entry['type'] is None:
            continue
        sandbox[key] = entry['value']

    return {
        'schema': 'safezone.sandbox-template/v1',
        'name': (name or '').strip() or f'{server_name} world',
        'description': (description or '').strip(),
        'sandbox': sandbox,
    }, None


def import_template(server_name, sandbox, expected_version=None):
    """Apply a world template's sandbox values to a server. ``(result, error)``.

    Blacklisted keys are filtered and reported under ``skipped`` rather than
    failing the import, mirroring the INI template importer.
    """
    if not isinstance(sandbox, dict) or not sandbox:
        return None, 'The template has no sandbox settings'
    if len(sandbox) > MAX_SANDBOX_SETTINGS:
        return None, f'A template may hold at most {MAX_SANDBOX_SETTINGS} settings'

    changes = {}
    skipped = []
    for key, value in sandbox.items():
        if is_template_excluded(key):
            skipped.append(key)
            continue
        changes[key] = value

    if not changes:
        return None, 'The template has no applicable settings (all were excluded)'

    result, error = write(server_name, changes, expected_version)
    if error:
        return None, error

    result['skipped'] = skipped
    return result, None

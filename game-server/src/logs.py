#!/usr/bin/env python3
"""Reading a game server's log.

The manager writes each server's stdout to `/tmp/game_server_<name>.log`. That
path is built from a database value, so exposing it over an API makes the name a
path-traversal vector: a server called `../../etc/passwd` would otherwise be
readable through the panel.

`SAFE_NAME` is therefore enforced in both directions - `manager_api` refuses to
create a server whose name is not safe, and `path_for` refuses to build a path
from one. Belt and braces, because the two run at different times and a row
predating the validation would still be here.
"""
import os
import re

LOG_DIR = '/tmp'
LOG_PREFIX = 'game_server_'

# Letters, digits, underscore, hyphen and dot - but never a path separator, and
# never a leading dot, so `..` can not be spelled.
SAFE_NAME = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$')

MAX_LINES = 2000
DEFAULT_LINES = 200
# Cap the tail read so a huge log cannot be pulled into memory in one go.
_READ_CHUNK = 256 * 1024


def is_safe_name(name):
    return bool(name) and bool(SAFE_NAME.match(str(name)))


def path_for(server_name):
    """Absolute log path for a server, or None if the name is not safe."""
    if not is_safe_name(server_name):
        return None
    filename = f'{LOG_PREFIX}{server_name}.log'
    # basename is belt-and-braces on top of the pattern above.
    return os.path.join(LOG_DIR, os.path.basename(filename))


def tail(server_name, lines=DEFAULT_LINES):
    """The last `lines` lines of a server's log.

    Returns ``(lines_list, error)``. Reads from the end rather than loading the
    file: a long-running server's log is not small.
    """
    try:
        lines = int(lines)
    except (TypeError, ValueError):
        lines = DEFAULT_LINES
    lines = max(1, min(lines, MAX_LINES))

    path = path_for(server_name)
    if not path:
        return [], 'That server name cannot be used to locate a log file'
    if not os.path.exists(path):
        return [], 'No log file yet - the server may never have started'

    try:
        with open(path, 'rb') as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            read_size = min(size, _READ_CHUNK)
            handle.seek(size - read_size)
            data = handle.read(read_size)
    except OSError as e:
        return [], f'Could not read the log: {e}'

    text = data.decode('utf-8', errors='replace')
    if read_size < size:
        # The first line is almost certainly cut in half by the seek.
        text = text.split('\n', 1)[-1]

    return text.splitlines()[-lines:], None

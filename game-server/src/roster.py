#!/usr/bin/env python3
"""Parsing of the PZ `players` console command output (pure, testable)."""
import re

# Matches the header the PZ `players` console command prints, e.g.
# "Players connected (2):" followed by lines like "-Username".
_PLAYERS_HEADER_RE = re.compile(r'Players connected\s*\((\d+)\)')
_PLAYER_LINE_RE = re.compile(r'^\s*-\s*(.+?)\s*$')


def parse_online_players(text):
    """Parse the online player list from server log output.

    Returns a list of usernames from the most recent "Players connected (N):"
    block in ``text``, or ``None`` if no such block is present (so callers can
    keep the previously known roster). An empty list means a block was found
    with zero players.
    """
    lines = text.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if _PLAYERS_HEADER_RE.search(line):
            header_idx = i  # keep the last occurrence

    if header_idx is None:
        return None

    names = []
    for line in lines[header_idx + 1:]:
        match = _PLAYER_LINE_RE.match(line)
        if not match:
            break
        names.append(match.group(1))
    return names

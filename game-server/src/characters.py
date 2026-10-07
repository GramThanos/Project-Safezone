#!/usr/bin/env python3
"""A linked character's saved data, read from the server's ``players.db``.

The game saves each character into ``Saves/Multiplayer/<server>/players.db``;
`zomboid_db_api` decodes it. This module only finds the file, keeps it parsed
between requests and picks out one account's character. What a given reader may
see is decided by the backend, which owns the accounts - this hands over the
whole report.

Two rules matter here:

* **A character is found by its owner, never by its name.** `PlayersDB.getPlayer`
  also matches a character's in-game name, and anyone may name their character
  after somebody else's account - which would hand them that account's data.
  `find` matches the account username (`getPlayersByOwner`) and nothing else.
* **The file is re-read only when it changes.** The game writes it when a
  character is saved, so most requests are answered from the parsed copy. The
  signature covers the WAL and the item dictionary as well, since either can
  change what a read returns without touching ``players.db`` itself.
"""
import datetime
import os
import threading

import backups
from zomboid_db_api import PlayersDB

PLAYERS_DB = 'players.db'
WORLD_DICTIONARY = 'WorldDictionary.bin'

# server name -> (signature, PlayersDB). A handful of servers at most, and each
# entry is replaced rather than added to when its file changes.
_cache = {}
_lock = threading.Lock()


class Unavailable(Exception):
    """No character data to give, with the HTTP status that says why."""

    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def _log(message):
    ts = datetime.datetime.now().isoformat()
    print(f"[{ts}][Characters] {message}")


def db_path(server_name):
    """The server's ``players.db``, or None if the name is unusable."""
    folder = backups.save_dir(server_name)
    return os.path.join(folder, PLAYERS_DB) if folder else None


def _stat(path):
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def signature(path):
    """What identifies one version of the save: the database, its WAL and the item names."""
    folder = os.path.dirname(path)
    return (_stat(path), _stat(path + '-wal'), _stat(os.path.join(folder, WORLD_DICTIONARY)))


def load(server_name):
    """``(PlayersDB, saved_at)`` for a server; raises `Unavailable`.

    ``saved_at`` is when the game last wrote the file (ISO, UTC) - the age of
    everything read from it.
    """
    path = db_path(server_name)
    if not path:
        raise Unavailable('Invalid server name', 400)

    sig = signature(path)
    if sig[0] is None:
        # A server that has never saved anyone: nothing yet, not a fault.
        raise Unavailable('The server has no saved characters yet', 404)

    with _lock:
        cached = _cache.get(server_name)
        if cached and cached[0] == sig:
            db = cached[1]
        else:
            try:
                db = PlayersDB(path)
            except Exception as e:  # a locked, half-written or foreign file
                _log(f'Could not read {path}: {e}')
                raise Unavailable('The character database could not be read', 503)
            _cache[server_name] = (sig, db)

    newest = max(s[0] for s in sig if s)
    saved_at = datetime.datetime.fromtimestamp(newest / 1e9, tz=datetime.timezone.utc)
    return db, saved_at.isoformat()


def find(db, username):
    """The account's main character (split-screen slot 1), or None.

    Matches the owner only - see the module docstring for why a character name
    must never match.
    """
    if not username:
        return None
    owned = db.getPlayersByOwner(username)
    for player in owned:
        if player.getSlot() == 1:
            return player
    return owned[0] if owned else None


def main_characters(db):
    """Each account's main character, the one `find` would pick for it.

    Slot 1 where the account has one, otherwise its first row - the same rule
    as `find`, applied to the whole file in one pass. Single-player rows (no
    owner) are left out.
    """
    mains = {}
    for player in db.getPlayers():
        owner = player.getOwner()
        if not owner:
            continue
        key = owner.lower()
        current = mains.get(key)
        if current is None or (player.getSlot() == 1 and current.getSlot() != 1):
            mains[key] = player
    return list(mains.values())


def summary(player):
    """The few numbers the coin system reads, without decoding a whole report.

    ``name`` is what tells one life from the next: a new character after a
    death has a new name, a restored backup brings an old one back.
    """
    return {
        'username': player.getOwner(),
        'name': player.getName(),
        'status': player.getStatus(),
        'zombie_kills': player.getZombieKills(),
        'hours_survived': player.getHoursSurvived(),
    }


def summaries(server_name):
    """``{'characters': [...], 'saved_at': ...}`` for every account on a server; raises `Unavailable`."""
    db, saved_at = load(server_name)
    out = []
    for player in main_characters(db):
        try:
            out.append(summary(player))
        except Exception as e:  # one unreadable character must not hide the rest
            _log(f'Could not summarise {player.getOwner()} on {server_name}: {e}')
    return {'characters': out, 'saved_at': saved_at}


def report(server_name, username):
    """``{'character': ..., 'saved_at': ...}`` for one account's character; raises `Unavailable`."""
    db, saved_at = load(server_name)

    player = find(db, username)
    if player is None:
        raise Unavailable('This character has not been saved on the server yet', 404)

    try:
        data = player.toDict()
    except Exception as e:  # the getters do not raise; this is the belt to their braces
        _log(f'Could not decode {username} on {server_name}: {e}')
        raise Unavailable('The character could not be decoded', 503)

    return {'character': data, 'saved_at': saved_at}

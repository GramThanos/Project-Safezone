"""Read Project Zomboid ``players.db`` files: every character, alive or dead.

::

    from zomboid_db_api import PlayersDB

    db = PlayersDB("Zomboid/Saves/Multiplayer/servertest/players.db")
    for p in db.getPlayers():
        print(p.getOwner(), p.getName(), p.getStatus(), p.getTimeAlive(), p.getLocation())

    p = db.getPlayer("thanos")        # owner username or character name
    p.getSkills(), p.getInventory(), p.getHealth()
    p.toDict()                        # everything at once

Or in one call: ``getPlayers(path)`` / ``getPlayer(path, name)``.

The file is opened read-only and closed right after reading.  Item names come
from the save's ``WorldDictionary.bin``, picked up automatically when it sits
next to ``players.db``.

Advanced: :func:`decode_player` decodes a character blob directly;
:func:`register_layout` and :func:`register_item_reader` teach the decoder
about save formats of future game versions (see :mod:`zomboid_db_api.versions`).
"""

from .accounts import Account, AuthResult, ServerDB
from .binary import DecodeError
from .decoder import decode_player
from .items import register_item_reader
from .players import Player, PlayersDB, WorldDictionary, getPlayer, getPlayers
from .state import PlayerState
from .versions import register_layout

__version__ = "0.2.0"

__all__ = [
    "Account",
    "AuthResult",
    "DecodeError",
    "Player",
    "PlayerState",
    "PlayersDB",
    "ServerDB",
    "WorldDictionary",
    "decode_player",
    "getPlayer",
    "getPlayers",
    "register_item_reader",
    "register_layout",
]

"""Read-only access to a Project Zomboid ``players.db``.

``players.db`` lives in the save folder (``Zomboid/Saves/Multiplayer/<server>/``
for a server, ``Zomboid/Saves/<mode>/<save>/`` for single player) and holds one
row per character: ``networkPlayers`` for multiplayer, ``localPlayers`` for
single player.  A dead character keeps its row (marked dead) until its owner
creates a new character, which overwrites it.

Usage::

    from zomboid_db_api import PlayersDB

    db = PlayersDB("Zomboid/Saves/Multiplayer/servertest/players.db")
    for p in db.getPlayers():
        print(p.getOwner(), p.getName(), p.getStatus(), p.getTimeAlive(), p.getLocation())

    thanos = db.getPlayer("thanos")          # owner username or character name
    thanos.getSkills(), thanos.getInventory(), thanos.toDict()

Opening reads every row in one query and closes the file straight away, so a
running server is never blocked.  The character data in each row is decoded
only when something inside it is asked for, and then cached.

Item names come from the save's ``WorldDictionary.bin`` (see
:class:`WorldDictionary`), which sits next to ``players.db``.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .binary import ByteReader, DecodeError
from .decoder import decode_player
from .report import character_report, format_hours, format_location
from .state import PlayerState

__all__ = ["Player", "PlayersDB", "WorldDictionary", "getPlayer", "getPlayers"]

PathLike = Union[str, "os.PathLike[str]"]
_STATUSES = (None, "alive", "dead")


# =============================================================================
# reading players.db
# =============================================================================

def _connect(path: Path) -> sqlite3.Connection:
    """Open the database so that nothing can be written (the game owns this file)."""
    if not path.is_file():
        raise FileNotFoundError(f"database not found: {path}")
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    conn.execute("PRAGMA query_only = ON")
    conn.row_factory = sqlite3.Row
    return conn


# _Row attribute -> column (lower case; the game's schema is matched case-insensitively,
# and columns that a table or game version lacks simply read as None).
_COLUMNS = {"id": "id", "world": "world", "username": "username", "player_index": "playerindex",
            "name": "name", "steam_id": "steamid", "x": "x", "y": "y", "z": "z",
            "world_version": "worldversion", "data": "data", "is_dead": "isdead"}


@dataclass
class _Row:
    """One row of ``networkPlayers`` / ``localPlayers``."""

    source: str  # "network" or "local"
    id: int
    name: Optional[str]
    is_dead: bool
    x: Optional[float]
    y: Optional[float]
    z: Optional[float]
    world_version: Optional[int]
    data: bytes
    world: Optional[str] = None
    username: Optional[str] = None
    player_index: Optional[int] = None
    steam_id: Optional[str] = None


def _row(source: str, row: sqlite3.Row) -> _Row:
    by_column = {k.lower(): row[k] for k in row.keys()}
    v = {attr: by_column.get(col) for attr, col in _COLUMNS.items()}
    return _Row(
        source=source, id=_int(v["id"]) or 0, name=_text(v["name"]), is_dead=_bool(v["is_dead"]),
        x=_float(v["x"]), y=_float(v["y"]), z=_float(v["z"]), world_version=_int(v["world_version"]),
        data=bytes(v["data"]) if v["data"] is not None else b"",
        world=_text(v["world"]), username=_text(v["username"]),
        player_index=_int(v["player_index"]), steam_id=_text(v["steam_id"]),
    )


def _bool(value: Any) -> bool:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", "replace")
    if isinstance(value, str):
        return value.strip().lower() in ("true", "t", "1", "yes", "y")
    return bool(value)


def _int(value: Any) -> Optional[int]:
    try:
        return None if value is None or value == "" else int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> Optional[float]:
    try:
        return None if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> Optional[str]:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", "replace")
    return None if value is None or value == "" else str(value)


# =============================================================================
# public API
# =============================================================================


class Player:
    """One character.

    Getters for the database row (owner, name, status, location, ...) are
    instant.  The others decode the character data on first use (a few
    milliseconds) and are cached.  Getters return plain values, lists and
    dicts; :meth:`toDict` returns everything at once.
    """

    def __init__(self, row: _Row, db: "PlayersDB"):
        self._row = row
        self._db = db
        self._state: Optional[PlayerState] = None
        self._report: Optional[Dict[str, Any]] = None

    def __repr__(self) -> str:
        return f"<Player {self.getName()!r} owner={self.getOwner()!r} {self.getStatus()}>"

    # -- from the database row (no decoding) -----------------------------------------
    def getOwner(self) -> Optional[str]:
        """Account username; ``None`` for a single-player character."""
        return self._row.username

    def getName(self) -> Optional[str]:
        """Character name, ``"Forename Surname"``."""
        if self._row.name:
            return self._row.name
        state = self.getState()
        return state.full_name

    def getStatus(self) -> str:
        """``"alive"`` or ``"dead"``."""
        return "dead" if self._row.is_dead else "alive"

    def isDead(self) -> bool:
        return self._row.is_dead

    def isAlive(self) -> bool:
        return not self._row.is_dead

    def isSinglePlayer(self) -> bool:
        return self._row.source == "local"

    def getSteamId(self) -> Optional[str]:
        return self._row.steam_id

    def getWorld(self) -> Optional[str]:
        return self._row.world

    def getSlot(self) -> Optional[int]:
        """Split-screen slot on the owner's machine (1 = main player)."""
        return None if self._row.player_index is None else self._row.player_index + 1

    def getX(self) -> Optional[float]:
        return self._row.x

    def getY(self) -> Optional[float]:
        return self._row.y

    def getZ(self) -> Optional[float]:
        return self._row.z

    def getLocation(self) -> Optional[str]:
        """``"x,y,z"`` in whole tiles (as map.projectzomboid.com and ``/teleportto`` use)."""
        return format_location(self._row.x, self._row.y, self._row.z)

    def getWorldVersion(self) -> Optional[int]:
        """Save-format version of this row (195 = Build 41.78, 219+ = Build 42)."""
        return self._row.world_version

    # -- decoded character data -----------------------------------------------------
    def getState(self) -> PlayerState:
        """The full decoded character (:class:`~zomboid_db_api.state.PlayerState`); never raises."""
        if self._state is None:
            r = self._row
            self._state = decode_player(r.data, r.world_version or 0, names=self._db._item_names())
        return self._state

    def toDict(self) -> Dict[str, Any]:
        """Everything about this character, in sections (see the README for the layout)."""
        if self._report is None:
            self._report = character_report(self._row, state=self.getState())
        return self._report

    def toJson(self, indent: Optional[int] = 2) -> str:
        return json.dumps(self.toDict(), indent=indent, ensure_ascii=False)

    def isDecoded(self) -> bool:
        """True when the character data was decoded completely."""
        return self.getState().complete

    def getDecodeErrors(self) -> List[str]:
        return list(self.getState().errors)

    def getHoursSurvived(self) -> Optional[float]:
        """In-game hours survived (for a dead character: how long it lived)."""
        return self.getState().hours_survived

    def getTimeAlive(self) -> Optional[str]:
        """``getHoursSurvived()`` as text, e.g. ``"6 days 18 hours"``."""
        return format_hours(self.getHoursSurvived())

    def getDaysSurvived(self) -> Optional[float]:
        return self.getState().days_survived

    def getZombieKills(self) -> Optional[int]:
        return self.getState().zombie_kills

    def getSurvivorKills(self) -> Optional[int]:
        return self.getState().survivor_kills

    def getGender(self) -> Optional[str]:
        return self.toDict()["character"]["gender"]

    def getProfession(self) -> Optional[str]:
        return self.toDict()["character"]["profession"]

    def getTraits(self) -> List[str]:
        return self.toDict()["character"]["traits"]

    def getSkills(self) -> Dict[str, Dict[str, float]]:
        """``{skill: {"level": int, "xp": float}}`` for every skill with progress."""
        return self.toDict()["skills"].get("perks", {})

    def getSkillLevel(self, skill: str) -> int:
        for name, value in self.getSkills().items():
            if name.lower() == skill.lower():
                return value["level"]
        return 0

    def isZombieInfected(self) -> Optional[bool]:
        return self.getState().is_zombie_infected

    def getHealth(self) -> Dict[str, Any]:
        """Injuries, all 17 body parts, and body fields (cold, infection timers, ...)."""
        return self.toDict()["health"]

    def getStats(self) -> Dict[str, float]:
        """Hunger, thirst, fatigue, panic, ... as stored (see ``toDict()`` for percentages)."""
        return dict(self.getState().stats)

    def getNutrition(self) -> Optional[Dict[str, float]]:
        return self.toDict()["condition"]["nutrition"]

    def getWornItems(self) -> List[Dict[str, Any]]:
        """``[{"slot", "name", "type", "item_id"}]``."""
        return self.toDict()["equipment"]["worn"]

    def getHands(self) -> Dict[str, Any]:
        """``{"primary_hand", "secondary_hand", "two_handed"}``."""
        eq = self.toDict()["equipment"]
        return {k: eq[k] for k in ("primary_hand", "secondary_hand", "two_handed")}

    def getInventory(self) -> List[Dict[str, Any]]:
        """Items carried; bags have their own ``"contents"`` list."""
        return self.toDict()["inventory"].get("items", [])

    def getItemCount(self) -> int:
        """Number of items carried, counting bag contents and stacks."""
        return self.toDict()["inventory"].get("item_count", 0)

    def getKnownRecipes(self) -> List[str]:
        return list(self.getState().known_recipes)

    def getModData(self) -> Dict[Any, Any]:
        """The character's Lua ``modData`` table (used by the game and by mods)."""
        return self.toDict()["mod_data"]


class PlayersDB:
    """A ``players.db`` file, read once and kept in memory.

    :param path: the ``players.db`` file.
    :param worldDictionary: path to the save's ``WorldDictionary.bin`` for item
        names.  By default the one next to ``players.db`` is used if it exists;
        pass ``False`` to never use one.
    """

    def __init__(self, path: PathLike, worldDictionary: Union[PathLike, bool, None] = None):
        self.path = Path(path)
        if worldDictionary is None:
            candidate = self.path.with_name("WorldDictionary.bin")
            self._dictionary_path: Optional[Path] = candidate if candidate.is_file() else None
        elif worldDictionary is False:
            self._dictionary_path = None
        else:
            self._dictionary_path = Path(worldDictionary)  # type: ignore[arg-type]
            if not self._dictionary_path.is_file():
                raise FileNotFoundError(f"WorldDictionary not found: {self._dictionary_path}")
        self._dictionary: Optional[WorldDictionary] = None
        self._dictionary_loaded = False
        self._players: List[Player] = []
        self.refresh()

    def __repr__(self) -> str:
        return f"<PlayersDB {self.path.name!r} {len(self._players)} characters>"

    def __enter__(self) -> "PlayersDB":
        return self

    def __exit__(self, *exc) -> None:
        pass  # nothing stays open

    def __len__(self) -> int:
        return len(self._players)

    def __iter__(self):
        return iter(self._players)

    def refresh(self) -> None:
        """Re-read the file (picks up changes the game made since opening)."""
        conn = _connect(self.path)
        try:
            tables = {r[0].lower(): r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            rows: List[_Row] = []
            if "networkplayers" in tables:
                rows += [_row("network", r) for r in conn.execute(
                    f'SELECT * FROM "{tables["networkplayers"]}" ORDER BY username, playerIndex, id')]
            if "localplayers" in tables:
                rows += [_row("local", r) for r in conn.execute(
                    f'SELECT * FROM "{tables["localplayers"]}" ORDER BY id')]
        finally:
            conn.close()
        self._players = [Player(r, self) for r in rows]

    def _item_names(self) -> Optional[WorldDictionary]:
        if not self._dictionary_loaded:
            self._dictionary_loaded = True
            if self._dictionary_path is not None:
                try:
                    self._dictionary = WorldDictionary.load(self._dictionary_path)
                except DecodeError:
                    self._dictionary = None
        return self._dictionary

    # -- queries ----------------------------------------------------------------------------
    def getPlayers(self, status: Optional[str] = None) -> List[Player]:
        """All characters (multiplayer and single player), optionally only ``"alive"`` or ``"dead"``."""
        if status not in _STATUSES:
            raise ValueError(f"status must be 'alive', 'dead' or None, not {status!r}")
        return [p for p in self._players if status is None or p.getStatus() == status]

    def getAlivePlayers(self) -> List[Player]:
        return self.getPlayers("alive")

    def getDeadPlayers(self) -> List[Player]:
        return self.getPlayers("dead")

    def getPlayer(self, name: str) -> Optional[Player]:
        """The character whose owner username or character name is ``name`` (case-insensitive).

        If the owner has several (split-screen) characters, the main one is returned;
        use :meth:`getPlayersByOwner` for all of them.
        """
        wanted = name.lower()
        for p in self._players:
            if (p._row.username or "").lower() == wanted:
                return p
        for p in self._players:
            if (p._row.name or "").lower() == wanted:
                return p
        return None

    def getPlayersByOwner(self, owner: str) -> List[Player]:
        return [p for p in self._players if (p._row.username or "").lower() == owner.lower()]

    def getPlayersBySteamId(self, steamId: Union[str, int]) -> List[Player]:
        return [p for p in self._players if p._row.steam_id == str(steamId)]

    def getOwners(self) -> List[str]:
        """Account usernames that have a character, sorted."""
        return sorted({p._row.username for p in self._players if p._row.username}, key=str.lower)

    def getPlayerCount(self, status: Optional[str] = None) -> int:
        return len(self.getPlayers(status))


def getPlayers(path: PathLike, status: Optional[str] = None,
               worldDictionary: Union[PathLike, bool, None] = None) -> List[Player]:
    """All characters in a ``players.db`` (shortcut for ``PlayersDB(path).getPlayers(status)``)."""
    return PlayersDB(path, worldDictionary).getPlayers(status)


def getPlayer(path: PathLike, name: str, worldDictionary: Union[PathLike, bool, None] = None) -> Optional[Player]:
    """One character by owner username or character name (shortcut for ``PlayersDB(path).getPlayer(name)``)."""
    return PlayersDB(path, worldDictionary).getPlayer(name)


# =============================================================================
# WorldDictionary.bin (item names)
# =============================================================================
#
# Character data refers to item types by a numeric registry id that is assigned
# per world; the names live in WorldDictionary.bin in the save folder.  Build 42
# prefixes the file with the world version, Build 41 does not; both are detected.
# Only the item table is read.

@dataclass
class DictionaryItem:
    registry_id: int
    module: str
    name: str
    mod_id: str = "pz-vanilla"
    is_modded: bool = False
    exists_as_vanilla: bool = False
    obsolete: bool = False
    removed: bool = False
    mod_overrides: List[str] = field(default_factory=list)

    @property
    def full_type(self) -> str:
        return f"{self.module}.{self.name}"


@dataclass
class WorldDictionary:
    items: Dict[int, DictionaryItem] = field(default_factory=dict)
    world_version: Optional[int] = None  # only stored by Build 42

    def full_type(self, registry_id: int) -> Optional[str]:
        """``Base.Axe`` for a registry id, or ``None`` if unknown."""
        item = self.items.get(registry_id)
        return item.full_type if item else None

    @classmethod
    def load(cls, path: Union[str, "os.PathLike[str]"]) -> "WorldDictionary":
        with open(path, "rb") as fh:
            return cls.from_bytes(fh.read())

    @classmethod
    def from_bytes(cls, data: bytes) -> "WorldDictionary":
        if len(data) < 7:
            raise DecodeError("WorldDictionary data is too short")
        first = int.from_bytes(data[:4], "big", signed=True)
        # Build 42 starts with a small world version; Build 41 with a short id
        # followed by more data, which reads as a large int.
        attempts = (True, False) if 0 < first < 65536 else (False, True)
        errors = []
        for versioned in attempts:
            try:
                return cls._parse(data, versioned)
            except DecodeError as exc:
                errors.append(f"{'B42' if versioned else 'B41'} format: {exc}")
        raise DecodeError("not a WorldDictionary file (" + "; ".join(errors) + ")")

    @classmethod
    def _parse(cls, data: bytes, versioned: bool) -> "WorldDictionary":
        r = ByteReader(data)
        wd = cls()
        if versioned:
            wd.world_version = r.i32()
        r.i16()  # next free item id
        r.i8()   # next object name id
        r.i32()  # next sprite name id
        mods = [r.string() for _ in range(r.count(min_item_size=2))]
        modules = [r.string() for _ in range(r.count(min_item_size=2))]
        for _ in range(r.count(min_item_size=5)):
            item = _read_item_info(r, mods, modules)
            wd.items[item.registry_id] = item
        return wd  # the tables after the items are not needed


def _index(r: ByteReader, table: List[str], what: str) -> str:
    start = r.pos
    i = r.i16() if len(table) > 127 else r.i8()
    if not 0 <= i < len(table):
        raise DecodeError(f"{what} index {i} out of range ({len(table)} known)", start)
    return table[i]


def _read_item_info(r: ByteReader, mods: List[str], modules: List[str]) -> DictionaryItem:
    registry_id = r.i16()
    module = _index(r, modules, "module")
    item = DictionaryItem(registry_id=registry_id, module=module, name=r.string())
    flags = r.u8()
    if flags & 1:
        item.mod_id = _index(r, mods, "mod")
        item.is_modded = True
    item.exists_as_vanilla = bool(flags & 2)
    item.obsolete = bool(flags & 4)
    item.removed = bool(flags & 8)
    if flags & 16:
        if flags & 32:
            item.mod_overrides = [_index(r, mods, "mod") for _ in range(max(r.i8(), 0))]
        else:
            item.mod_overrides = [_index(r, mods, "mod")]
    return item

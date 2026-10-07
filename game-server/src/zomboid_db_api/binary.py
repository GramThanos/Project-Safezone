"""Low-level reading of the game's binary data.

:class:`ByteReader` mirrors ``java.nio.ByteBuffer`` (big-endian) as Project
Zomboid uses it; :func:`read_lua_table` reads a serialized Lua table
(``KahluaTableImpl.save``), which is how ``modData`` is stored.
"""

from __future__ import annotations

import math
import struct
from typing import Any, Dict, Optional, Union

__all__ = ["DIRECTIONS", "ByteReader", "DecodeError", "lua_to_python", "read_lua_table"]

# zombie.iso.IsoDirections, by index.
DIRECTIONS = ("N", "NW", "W", "SW", "S", "SE", "E", "NE")

_I16 = struct.Struct(">h")
_U16 = struct.Struct(">H")
_I32 = struct.Struct(">i")
_I64 = struct.Struct(">q")
_F32 = struct.Struct(">f")
_F64 = struct.Struct(">d")


class DecodeError(ValueError):
    """Raised when bytes do not match the expected layout."""

    def __init__(self, message: str, offset: Optional[int] = None):
        self.offset = offset
        super().__init__(message if offset is None else f"{message} (at byte {offset})")


class ByteReader:
    """Sequential reader over ``data[pos:end]``.

    Every read is bounds-checked against ``end`` so a nested reader (for a
    length-prefixed item, say) can never run into the bytes that follow it.
    Booleans must be exactly 0 or 1 and strings must be valid UTF-8: the game
    always writes them that way, so anything else means the layout is wrong.
    """

    __slots__ = ("data", "pos", "end")

    def __init__(self, data: bytes, pos: int = 0, end: Optional[int] = None):
        self.data = data
        self.pos = pos
        self.end = len(data) if end is None else end
        if not 0 <= self.pos <= self.end <= len(data):
            raise DecodeError(f"invalid reader window {pos}..{end} for {len(data)} bytes")

    @property
    def remaining(self) -> int:
        return self.end - self.pos

    def at_end(self) -> bool:
        return self.pos == self.end

    def _need(self, n: int) -> int:
        start = self.pos
        if n < 0 or start + n > self.end:
            raise DecodeError(f"need {n} bytes, {self.end - start} left", start)
        self.pos = start + n
        return start

    def skip(self, n: int) -> None:
        self._need(n)

    def take(self, n: int) -> bytes:
        start = self._need(n)
        return self.data[start:start + n]

    def window(self, n: int) -> "ByteReader":
        """Return a reader over the next ``n`` bytes and advance past them."""
        start = self._need(n)
        return ByteReader(self.data, start, start + n)

    def u8(self) -> int:
        return self.data[self._need(1)]

    def i8(self) -> int:
        v = self.u8()
        return v - 256 if v > 127 else v

    def bool(self) -> bool:
        start = self._need(1)
        v = self.data[start]
        if v > 1:
            raise DecodeError(f"expected boolean, got {v}", start)
        return v == 1

    def i16(self) -> int:
        return _I16.unpack_from(self.data, self._need(2))[0]

    def u16(self) -> int:
        return _U16.unpack_from(self.data, self._need(2))[0]

    def i32(self) -> int:
        return _I32.unpack_from(self.data, self._need(4))[0]

    def i64(self) -> int:
        return _I64.unpack_from(self.data, self._need(8))[0]

    def f32(self) -> float:
        """A float, returned as the shortest decimal that round-trips (0.3, not 0.30000001)."""
        start = self._need(4)
        v = _F32.unpack_from(self.data, start)[0]
        if v == 0.0 or not math.isfinite(v):
            return v
        raw = self.data[start:start + 4]
        for digits in (6, 7, 8):
            short = float(f"{v:.{digits}g}")
            if _F32.pack(short) == raw:
                return short
        return v

    def finite_f32(self) -> float:
        start = self.pos
        v = self.f32()
        if not math.isfinite(v):
            raise DecodeError(f"expected finite float, got {v}", start)
        return v

    def f64(self) -> float:
        return _F64.unpack_from(self.data, self._need(8))[0]

    def string(self) -> str:
        """``GameWindow.WriteString``: signed 16-bit byte length, then UTF-8."""
        start = self.pos
        n = self.i16()
        if n <= 0:
            return ""
        raw = self.take(n)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DecodeError(f"invalid UTF-8 string of {n} bytes", start) from exc

    def count(self, limit: int = 1_000_000, *, min_item_size: int = 1) -> int:
        """Read an ``int`` collection size and sanity-check it against the bytes left."""
        start = self.pos
        n = self.i32()
        if n < 0 or n > limit or n * min_item_size > self.remaining:
            raise DecodeError(f"implausible element count {n}", start)
        return n


# -- Lua tables -------------------------------------------------------------------
#
# ``KahluaTableImpl.save`` writes an ``int`` entry count, then key/value pairs,
# each value prefixed by a type byte: 0 string, 1 number (double), 2 nested
# table, 3 boolean; 4 (size-prefixed item) and 5 (direction byte) only appear
# in the network variant.  Lua has one number type, so integral doubles are
# returned as ``int``.

_STRING, _NUMBER, _TABLE, _BOOLEAN, _ITEM, _DIRECTION = range(6)
_MAX_DEPTH = 64


def _lua_value(r: ByteReader, depth: int) -> Any:
    start = r.pos
    tag = r.i8()
    if tag == _STRING:
        return r.string()
    if tag == _NUMBER:
        v = r.f64()
        return int(v) if v.is_integer() and abs(v) < 2**53 else v
    if tag == _TABLE:
        return read_lua_table(r, _depth=depth + 1)
    if tag == _BOOLEAN:
        return r.bool()
    if tag == _ITEM:  # kept opaque
        size = r.count(min_item_size=1)
        r.skip(size)
        return {"$item_bytes": size}
    if tag == _DIRECTION:
        d = r.u8()
        return DIRECTIONS[d] if d < len(DIRECTIONS) else d
    raise DecodeError(f"unknown Lua value tag {tag}", start)


def read_lua_table(r: ByteReader, *, _depth: int = 0) -> Dict[Union[str, int, float, bool], Any]:
    if _depth > _MAX_DEPTH:
        raise DecodeError("Lua table nesting too deep", r.pos)
    table: Dict[Union[str, int, float, bool], Any] = {}
    for _ in range(r.count(min_item_size=4)):
        key = _lua_value(r, _depth)
        if isinstance(key, dict):
            raise DecodeError("table used as Lua table key", r.pos)
        table[key] = _lua_value(r, _depth)
    return table


def lua_to_python(value: Any) -> Any:
    """Turn array-like tables (keys ``1..n``) into lists, recursively."""
    if not isinstance(value, dict):
        return value
    converted = {k: lua_to_python(v) for k, v in value.items()}
    keys = list(converted)
    if keys and all(isinstance(k, int) and not isinstance(k, bool) for k in keys) \
            and sorted(keys) == list(range(1, len(keys) + 1)):
        return [converted[i] for i in range(1, len(keys) + 1)]
    return converted

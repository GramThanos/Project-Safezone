"""Everything ``players.db`` holds about one character, as one ``dict``.

:func:`character_report` merges the database row (owner, alive/dead, location)
with the decoded character data into JSON-ready sections, without the
duplication of the raw decode (worn items and hands refer to inventory items by
name instead of repeating them).  Decoder details go to a ``decoding`` section.
This is what :meth:`zomboid_db_api.Player.toDict` returns.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any, Dict, Optional

from .binary import lua_to_python
from .state import Container, Item, PlayerState
from .versions import build_name

__all__ = ["STAT_RANGES", "character_report", "format_hours", "format_location", "to_jsonable"]

# Build 42 stat ranges (zombie.characters.CharacterStat): name -> (min, max).
STAT_RANGES = {
    "anger": (0, 1), "boredom": (0, 100), "discomfort": (0, 100), "endurance": (0, 1), "fatigue": (0, 1),
    "fitness": (-1, 1), "food_sickness": (0, 100), "hunger": (0, 1), "idleness": (0, 1),
    "intoxication": (0, 100), "morale": (0, 1), "nicotine_withdrawal": (0, 0.51), "pain": (0, 100),
    "panic": (0, 100), "poison": (0, 100), "sanity": (0, 1), "sickness": (0, 1), "stress": (0, 1),
    "temperature": (20, 40), "thirst": (0, 1), "unhappiness": (0, 100), "wetness": (0, 100),
    "zombie_fever": (0, 100), "zombie_infection": (0, 100),
}
# IsoPlayer.setExtraInfoFlags bits.
_ADMIN_FLAGS = ((1, "god_mode"), (2, "ghost_mode"), (4, "invisible"), (8, "no_clip"),
                (16, "show_admin_tag"), (32, "can_hear_all"))


def to_jsonable(obj: Any) -> Any:
    """Recursively convert data classes, tuples and sets to plain dicts and lists.

    Properties listed in a class's ``_json_properties`` are included; bytes are
    dropped and non-finite floats become ``None``.
    """
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        out = {f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
        for name in getattr(type(obj), "_json_properties", ()):
            out[name] = to_jsonable(getattr(obj, name))
        return out
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, (bytes, bytearray)):
        return None
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def format_location(x: Optional[float], y: Optional[float], z: Optional[float]) -> Optional[str]:
    """``"x,y,z"`` in whole tiles, as map.projectzomboid.com and ``/teleportto`` use."""
    if x is None or y is None:
        return None
    return f"{math.floor(x)},{math.floor(y)},{math.floor(z or 0)}"


def format_hours(hours: Optional[float]) -> Optional[str]:
    """``163.4`` -> ``"6 days 19 hours"`` (in-game time)."""
    if hours is None or not math.isfinite(hours) or hours < 0:
        return None
    if hours < 1:
        return f"{int(hours * 60)} min"
    days, rest = divmod(int(hours), 24)
    parts = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if rest or not days:
        parts.append(f"{rest} hour{'s' if rest != 1 else ''}")
    return " ".join(parts)


def character_report(record, *, state: PlayerState) -> Dict[str, Any]:
    """All per-character data from a ``players.db`` row and its decoded ``state``, as JSON-ready sections."""
    st = state
    hours = st.hours_survived
    d = st.descriptor
    report: Dict[str, Any] = {
        "owner": {
            "username": record.username,
            "steam_id": record.steam_id,
            "world": record.world,
            "split_screen_slot": None if record.player_index is None else record.player_index + 1,
            "table": f"{'networkPlayers' if record.source == 'network' else 'localPlayers'} row {record.id}",
        },
        "character": {
            "name": record.name or st.full_name,
            "forename": d.forename if d else None,
            "surname": d.surname if d else None,
            "gender": None if d is None else ("female" if d.female else "male"),
            "profession": d.profession if d else None,
            "traits": st.skills.traits if st.skills else [],
            "starting_skill_bonuses": d.xp_boosts if d else {},
            "descriptor_extras": d.extras if d else [],
            "display_name": st.display_name,
        },
        "status": {
            "status": "dead" if record.is_dead else "alive",
            "hours_survived": hours,
            "time_alive": format_hours(hours),
            "days_survived": None if hours is None else round(st.days_survived, 2),
            "zombie_kills": st.zombie_kills,
            "survivor_kills": st.survivor_kills,
            "zombie_infected": st.is_zombie_infected,
            "asleep": st.asleep,
            "on_fire": st.on_fire,
            "in_vehicle": st.vehicle is not None,
        },
        "location": {
            "x": record.x, "y": record.y, "z": record.z,
            "location": format_location(record.x, record.y, record.z),
            "facing": st.direction,
            "vehicle": to_jsonable(st.vehicle),
        },
        "health": _health(st),
        "condition": _condition(st),
        "skills": _skills(st),
        "equipment": _equipment(st),
        "inventory": _inventory(st.inventory),
        "knowledge": {
            "known_recipes": st.known_recipes,
            "skill_books_read": st.read_books,              # book -> pages read
            "literature_read": st.read_literature,          # magazines, novels -> value as saved
            "print_media_read": st.read_print_media,        # flyers, newspapers
            "books_finished": st.already_read_books,
            "tv_radio_lines_heard": st.known_media_lines,
            "craft_history": st.craft_history,              # last_craft_time in in-game hours
        },
        "appearance": _appearance(st),
        "other": _other(st),
        "mod_data": lua_to_python(st.mod_data) if st.mod_data else {},
        "decoding": {
            "world_version": st.world_version,
            "build": build_name(st.world_version),
            "layout": st.layout,
            "confidence": st.confidence,
            "complete": st.complete,
            "bytes": st.blob_size,
            "errors": st.errors,
            "warnings": st.warnings,
        },
    }
    return to_jsonable(report)


def _health(st: PlayerState) -> Dict[str, Any]:
    body = st.body
    if body is None:
        return {}
    injured = [{"part": p.name, "health": p.health, "conditions": p.conditions} for p in body.injured_parts()]
    return {
        "injuries": injured,
        "zombie_infected": st.is_zombie_infected,
        "body_parts": [to_jsonable(p) for p in body.parts],
        "body": body.fields,
        "thermoregulator": body.thermoregulator,
    }


def _stat_value(name: str, value: float, named_stats: bool) -> Dict[str, Any]:
    out: Dict[str, Any] = {"value": value}
    rng = STAT_RANGES.get(name) if named_stats else None
    if rng and rng[0] >= 0 and name != "temperature" and math.isfinite(value):
        lo, hi = rng
        out["percent"] = round(100.0 * (value - lo) / (hi - lo), 1)
    return out


def _condition(st: PlayerState) -> Dict[str, Any]:
    named = "zombie_infection" in st.stats  # Build 42 named stats
    return {
        "stats": {k: _stat_value(k, v, named) for k, v in st.stats.items()},
        "nutrition": to_jsonable(st.nutrition),
        "medication_effects": st.effects,
        "reduce_infection_power": st.reduce_infection_power,
    }


def _skills(st: PlayerState) -> Dict[str, Any]:
    s = st.skills
    if s is None:
        return {}
    perks = sorted(set(s.levels) | set(s.xp))
    return {
        "perks": {p: {"level": s.levels.get(p, 0), "xp": s.xp.get(p, 0.0)} for p in perks},
        "xp_multipliers": s.multipliers,
    }


def _item_ref(item: Optional[Item]) -> Optional[Dict[str, Any]]:
    if item is None:
        return None
    return {"name": item.display_name, "type": item.full_type, "item_id": item.id}


def _equipment(st: PlayerState) -> Dict[str, Any]:
    primary, secondary = st.primary_hand, st.secondary_hand
    return {
        "worn": [{"slot": w.location, **(_item_ref(w.item) or {"name": None})} for w in st.worn],
        "primary_hand": _item_ref(primary),
        "secondary_hand": _item_ref(secondary),
        "two_handed": primary is not None and primary is secondary,
    }


def _item(item: Item) -> Dict[str, Any]:
    d: Dict[str, Any] = {"name": item.display_name, "type": item.full_type, "kind": item.kind}
    if item.count > 1:
        d["count"] = item.count
    if item.condition is not None:
        d["condition"] = item.condition
    if item.uses != 1:
        d["uses"] = item.uses
    if item.used_delta is not None:
        d["fill"] = item.used_delta
    for flag in ("favorite", "infected", "activated"):
        if getattr(item, flag):
            d[flag] = True
    for key in ("key_id", "attached_slot", "attached_slot_type", "attached_to_model"):
        value = getattr(item, key)
        if value is not None:
            d[key] = value
    if item.current_ammo_count:
        d["ammo"] = item.current_ammo_count
    if item.details:
        d["details"] = item.details
    extra = {k: v for k, v in item.extra.items() if k not in ("kind_inferred",)}
    if "components" in extra:
        extra["components"] = [c["type"] for c in extra["components"]]
    if extra:
        d["properties"] = extra
    if item.mod_data:
        d["mod_data"] = lua_to_python(item.mod_data)
    if item.contents is not None:
        d["container"] = {"type": item.contents.type, "capacity": item.contents.capacity,
                          "weight_reduction": item.contents.weight_reduction}
        d["contents"] = [_item(i) for i in item.contents.items]
    d["registry_id"] = item.registry_id
    d["item_id"] = item.id
    if item.undecoded:
        d["undecoded"] = item.undecoded
    return d


def _inventory(inv: Optional[Container]) -> Dict[str, Any]:
    if inv is None:
        return {}
    return {"item_count": inv.total_count(), "capacity": inv.capacity, "items": [_item(i) for i in inv.items]}


def _appearance(st: PlayerState) -> Dict[str, Any]:
    v = st.visual
    d = st.descriptor
    out: Dict[str, Any] = {"body_model": d.torso if d else None,
                           "voice": None if d is None else {"prefix": d.voice_prefix, "pitch": d.voice_pitch,
                                                            "type": d.voice_type}}
    if v is not None:
        out.update(hair_model=v.hair_model, hair_color=v.hair_color, natural_hair_color=v.natural_hair_color,
                   beard_model=v.beard_model, beard_color=v.beard_color, natural_beard_color=v.natural_beard_color,
                   skin_texture=v.skin_texture_name or v.skin_texture, skin_color=v.skin_color,
                   body_hair=v.body_hair, blood=v.blood, dirt=v.dirt, holes=v.holes,
                   body_visuals=[to_jsonable(bv) for bv in v.body_visuals])
    return out


def _other(st: PlayerState) -> Dict[str, Any]:
    admin = None
    if st.extra_info_flags is not None:
        admin = {name: bool(st.extra_info_flags & bit) for bit, name in _ADMIN_FLAGS}
    elif st.no_clip is not None:
        admin = {"no_clip": st.no_clip}
    return {
        "chat": {"tag_prefix": st.tag_prefix, "tag_color": st.tag_color, "show_tag": st.show_tag,
                 "all_chat_muted": st.all_chat_muted, "faction_pvp": st.faction_pvp},
        "auto_drink": st.auto_drink,
        "admin_flags": admin,
        "cheats": st.cheats,
        "player_cheats": st.player_cheats,
        "sneaking": st.sneaking,
        "death_drag_down": st.death_drag_down,
        "timers": {"last_hour_slept": st.last_hour_slept, "force_wake_up_time": st.force_wake_up_time,
                   "time_since_last_smoke": st.time_since_last_smoke, "beard_grow_timing": st.beard_grow_timing,
                   "hair_grow_timing": st.hair_grow_timing, "last_animal_pet": st.last_animal_pet},
        "fitness": st.fitness,
        "vehicle_parts_repaired": st.mechanics_items,
    }

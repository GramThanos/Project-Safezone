"""Decoder for the ``data`` blob of ``networkPlayers`` / ``localPlayers`` rows.

The blob is the output of ``IsoPlayer.save(ByteBuffer)``: a single sequential,
big-endian record with no field tags, written by the class chain
``IsoMovingObject -> IsoGameCharacter -> IsoPlayer``::

    header       serialize flag, class id, offset, x/y/z, direction, modData
    descriptor   SurvivorDesc: name, gender, profession, ...
    visual       HumanVisual: hair, beard, skin, blood/dirt
    inventory    ItemContainer with every carried item (bags nested)
    sleep        asleep flag, forced wake-up time
    ---------------------------------------------- "tail" from here on
    stats        hunger, thirst, panic, ...
    body         17 body parts + BodyDamage fields + Thermoregulator
    skills       traits, XP and perk levels
    character    hand indices, effects, read books, recipes, cheats, ...
    player       hours survived, kills, worn items, nutrition, fitness, ...

Because nothing is tagged, one wrong guess shifts every following byte.  The
decoder therefore validates as it goes (booleans must be 0/1, strings valid
UTF-8, counts must fit) and only calls a decode *complete* when it ends on the
blob's last byte.  When the layout of a world version is not known for sure
(see :mod:`zomboid_db_api.versions`) it tries candidate layouts and keeps the one
that decodes exactly; when the prefix cannot be decoded at all it scans for
the tail instead.  It never raises on bad data: what could not be decoded is
listed in ``PlayerState.errors``.
"""

from __future__ import annotations

import copy
import itertools
import math
import struct
from typing import Callable, Dict, List, Optional, Tuple

from .binary import DIRECTIONS, ByteReader, DecodeError, read_lua_table
from .items import DecodeContext, ItemNameResolver, read_container, read_item_visual
from .state import (
    BodyDamage, BodyPart, Descriptor, HumanVisual, Nutrition, PlayerState, Skills, VehicleSeat, WornItem,
)
from .versions import Features, LayoutPlan, plan_for

__all__ = ["BODY_PARTS", "decode_player"]

BODY_PARTS = ("Hand_L", "Hand_R", "ForeArm_L", "ForeArm_R", "UpperArm_L", "UpperArm_R",
              "Torso_Upper", "Torso_Lower", "Head", "Neck", "Groin", "UpperLeg_L",
              "UpperLeg_R", "LowerLeg_L", "LowerLeg_R", "Foot_L", "Foot_R")

_STATS_V1 = ("anger", "boredom", "endurance", "fatigue", "fitness", "hunger", "morale", "stress",
             "fear", "panic", "sanity", "sickness", "boredom_legacy", "pain", "drunkenness", "thirst")
_STATS_V2 = ("anger", "boredom", "discomfort", "endurance", "fatigue", "fitness", "food_sickness",
             "hunger", "idleness", "intoxication", "morale", "nicotine_withdrawal", "pain", "panic",
             "poison", "sanity", "sickness", "stress", "temperature", "thirst", "unhappiness",
             "wetness", "zombie_fever", "zombie_infection")
_EFFECTS = ("depress_effect", "depress_first_take_time", "beta_effect", "beta_delta",
            "pain_effect", "pain_delta", "sleeping_tablet_effect", "sleeping_tablet_delta")
_BODY_MAIN_V1: Tuple[Tuple[str, str], ...] = (
    ("infection_level", "f"), ("fake_infection_level", "f"), ("wetness", "f"), ("catch_a_cold", "f"),
    ("has_a_cold", "b"), ("cold_strength", "f"), ("unhappyness_level", "f"), ("boredom_level", "f"),
    ("food_sickness_level", "f"), ("poison_level", "f"), ("temperature", "f"),
    ("reduce_fake_infection", "b"), ("health_from_food_timer", "f"), ("pain_reduction", "f"),
    ("cold_reduction", "f"), ("infection_time", "f"), ("infection_mortality_duration", "f"),
    ("cold_damage_stage", "f"))
_BODY_MAIN_V2: Tuple[Tuple[str, str], ...] = (
    ("catch_a_cold", "f"), ("has_a_cold", "b"), ("cold_strength", "f"), ("time_to_sneeze_or_cough", "i"),
    ("reduce_fake_infection", "b"), ("health_from_food_timer", "f"), ("pain_reduction", "f"),
    ("cold_reduction", "f"), ("infection_time", "f"), ("infection_mortality_duration", "f"),
    ("cold_damage_stage", "f"))
_THERMO_V1 = ("set_point", "metabolic_rate", "metabolic_target", "body_heat_delta",
              "core_heat_delta", "thermal_damage", "damage_counter")
_THERMO_NODE_V1: Tuple[str, ...] = ("celsius", "skin_celsius", "heat_delta", "primary_delta", "secondary_delta")
# zombie.characters.CheatType, by ordinal (Build 42 player cheat list).
PLAYER_CHEAT_TYPES = ("god_mode", "invisible", "unlimited_endurance", "unlimited_ammo", "know_all_recipes",
                      "unlimited_carry", "build", "farming", "fishing", "health", "mechanics", "fast_move",
                      "movables", "timed_action_instant", "brush_tool", "no_clip", "can_see_everyone",
                      "can_hear_everyone", "zombies_dont_attack", "show_mp_info", "loot_tool",
                      "debug_context_menu")

_MAX_RECOVERY_CANDIDATES = 9
_learned: Dict[int, Features] = {}  # world version -> layout found by probing


# =============================================================================
# public entry point
# =============================================================================

def decode_player(blob: bytes, world_version: int, *, names: Optional[ItemNameResolver] = None,
                  features: Optional[Features] = None) -> PlayerState:
    """Decode a character blob (never raises on bad data).

    :param blob: the ``data`` column.
    :param world_version: the ``worldversion`` column of the same row.
    :param names: optional item-name resolver, e.g. a
        :class:`~zomboid_db_api.WorldDictionary`, to turn item registry ids into
        names such as ``Base.Axe``.
    :param features: force a specific layout instead of the version registry.
    """
    data = bytes(blob)
    wv = int(world_version)
    if features is not None:
        plan = LayoutPlan(wv, features, (), "custom", "layout supplied by caller")
    else:
        plan = plan_for(wv)
        learned = _learned.get(wv)
        if learned is not None and learned != plan.primary:
            plan = LayoutPlan(wv, learned, plan.probe, "probed",
                              "using the layout found by probing an earlier blob of this version")

    state = PlayerState(world_version=wv, blob_size=len(data), confidence=plan.confidence)
    if plan.note and plan.confidence not in ("exact", "gated"):
        state.warnings.append(plan.note)

    ctx = DecodeContext(plan.primary, names)
    prefix_end, failed_at = _run(_PREFIX_SECTIONS, ByteReader(data), state, ctx, strict=False)
    if prefix_end is not None:
        state.stats_offset = prefix_end
        _decode_tail(data, prefix_end, state, plan, names)
    else:
        _recover_tail(data, failed_at, state, plan, names)

    _resolve_references(state)
    return state


# =============================================================================
# driver
# =============================================================================

Section = Tuple[str, Callable[[ByteReader, PlayerState, DecodeContext, bool], None]]


def _run(sections: Tuple[Section, ...], r: ByteReader, state: PlayerState, ctx: DecodeContext,
         strict: bool) -> Tuple[Optional[int], int]:
    """Run sections in order.

    Returns ``(end_offset, -1)`` on success, or ``(None, start_of_failed_section)``
    after recording the error on ``state``.
    """
    for name, fn in sections:
        start = r.pos
        try:
            fn(r, state, ctx, strict)
        except DecodeError as exc:
            state.errors.append(f"{name} section (starting at byte {start}): {exc}")
            state.bytes_decoded = max(state.bytes_decoded, start)
            return None, start
        state.bytes_decoded = r.pos
    return r.pos, -1


def _layout_label(features: Features, plan: LayoutPlan) -> str:
    label = f"{features.family} (world version {features.world_version})"
    diff = features.differences(plan_for(features.world_version).primary) if plan.confidence != "custom" else {}
    if diff:
        label += "; " + ", ".join(f"{k}={v}" for k, v in sorted(diff.items()))
    return label


def _decode_tail(data: bytes, start: int, state: PlayerState, plan: LayoutPlan,
                 names: Optional[ItemNameResolver]) -> None:
    """Decode Stats..end, trying candidate layouts until one ends exactly on the last byte."""
    best: Optional[PlayerState] = None
    best_features = plan.primary
    tried = 0
    for i, features in enumerate(plan.candidates()):
        tried += 1
        trial = copy.copy(state)
        trial.errors = list(state.errors)
        trial.warnings = list(state.warnings)
        r = ByteReader(data, start)
        # The primary layout of a well-known version is trusted; anything we are
        # guessing at gets plausibility checks so a wrong guess fails fast.
        strict = i > 0 or plan.confidence not in ("exact", "gated", "legacy")
        end, _ = _run(_TAIL_SECTIONS, r, trial, DecodeContext(features, names), strict)
        if end is not None and end != len(data):
            trial.errors.append(f"decoded up to byte {end} but the blob has {len(data)} bytes "
                                f"({len(data) - end} left over)")
        if end == len(data):
            best, best_features = trial, features
            if i > 0 or plan.confidence in ("probed", "extrapolated"):
                _learned[state.world_version] = features
            break
        if best is None or trial.bytes_decoded > best.bytes_decoded:
            best, best_features = trial, features

    assert best is not None
    best.complete = not best.errors
    best.layout = _layout_label(best_features, plan)
    if best.complete and best_features is not plan.primary:
        best.confidence = "probed"
        best.warnings.append("layout determined by probing: " + best.layout)
    elif not best.complete and tried > 1:
        best.warnings.append(f"none of {tried} candidate layouts decoded the blob completely; "
                             f"showing the one that got furthest")
    state.__dict__.update(best.__dict__)


def _recover_tail(data: bytes, floor: int, state: PlayerState, plan: LayoutPlan,
                  names: Optional[ItemNameResolver]) -> None:
    """The prefix failed at ``floor``: find the unique offset from which the tail decodes exactly."""
    state.layout = _layout_label(plan.primary, plan)
    for features in itertools.islice(plan.candidates(), _MAX_RECOVERY_CANDIDATES):
        n_stats = len(_STATS_V2) if features.stats_named else len(_STATS_V1) + features.stats_cigarettes
        fmt = struct.Struct(f">{n_stats}f")
        hits: List[Tuple[int, PlayerState]] = []
        for off in range(floor, len(data) - fmt.size):
            values = fmt.unpack_from(data, off)
            if not all(math.isfinite(v) and -1e4 < v < 1e4 for v in values):
                continue
            trial = copy.copy(state)
            trial.errors, trial.warnings = [], []
            r = ByteReader(data, off)
            if _run(_TAIL_SECTIONS, r, trial, DecodeContext(features, names), True)[0] == len(data):
                hits.append((off, trial))
                if len(hits) > 1:
                    break
        if len(hits) == 1:
            off, trial = hits[0]
            prefix_errors = list(state.errors)
            state.__dict__.update(trial.__dict__)
            state.errors = prefix_errors
            state.warnings.append(f"inventory/appearance could not be decoded; character data "
                                  f"recovered from byte {off} onwards")
            state.recovered_tail = True
            state.stats_offset = off
            state.bytes_decoded = len(data)
            state.layout = _layout_label(features, plan)
            return
        if len(hits) > 1:
            state.warnings.append("tail recovery found more than one candidate offset; not used")
            return
    state.warnings.append("tail recovery found no matching offset")


def _resolve_references(state: PlayerState) -> None:
    if state.inventory is None:
        return
    flat = state.inventory.flat()
    for worn in state.worn:
        if 0 <= worn.index < len(flat):
            worn.item = flat[worn.index]


# =============================================================================
# prefix sections
# =============================================================================

def _header(r: ByteReader, st: PlayerState, ctx: DecodeContext, strict: bool) -> None:
    r.bool()  # IsoObject.Serialize()
    st.class_id = r.u8()
    st.offset_x = r.f32()
    st.offset_y = r.f32()
    st.x, st.y, st.z = r.f32(), r.f32(), r.f32()
    start = r.pos
    direction = r.i32()
    if not 0 <= direction <= 8:
        raise DecodeError(f"invalid direction {direction}", start)
    st.direction = DIRECTIONS[direction] if direction < 8 else None
    if r.u8():
        st.mod_data = read_lua_table(r)


def _read_perk(r: ByteReader, f: Features) -> str:
    return r.string() if f.perks_as_strings else f"perk#{r.i32()}"


def _int_flag(r: ByteReader) -> bool:
    start = r.pos
    v = r.i32()
    if v not in (0, 1):
        raise DecodeError(f"expected 0/1 int flag, got {v}", start)
    return v == 1


def _descriptor(r: ByteReader, st: PlayerState, ctx: DecodeContext, strict: bool) -> None:
    f = ctx.features
    if not r.bool():
        return
    d = Descriptor(id=r.i32(), forename=r.string(), surname=r.string(), torso=r.string(),
                   female=_int_flag(r), profession=r.string())
    if _int_flag(r):
        d.extras = [r.string() for _ in range(r.count(min_item_size=2))]
    for _ in range(r.count(min_item_size=6)):
        perk = _read_perk(r, f)
        d.xp_boosts[perk] = r.i32()
    if f.descriptor_voice:
        d.voice_prefix = r.string()
        d.voice_pitch = r.f32()
        d.voice_type = r.i32()
    st.descriptor = d


def _rgb(r: ByteReader) -> Tuple[int, int, int]:
    return (r.u8(), r.u8(), r.u8())


def _bytes_list(r: ByteReader) -> List[int]:
    n = r.i8()
    return list(r.take(n)) if n > 0 else []


def _visual(r: ByteReader, st: PlayerState, ctx: DecodeContext, strict: bool) -> None:
    f = ctx.features
    v = HumanVisual()
    flags = r.u8()
    if flags & 4:
        v.hair_color = _rgb(r)
    if flags & 2:
        v.beard_color = _rgb(r)
    if flags & 8:
        v.skin_color = _rgb(r)
    v.body_hair = r.i8()
    v.skin_texture = r.i8()
    if f.human_visual_rot_stage:
        v.zombie_rot_stage = r.i8()
    if flags & 64:
        v.skin_texture_name = r.string()
    if flags & 16:
        v.beard_model = r.string()
    if flags & 32:
        v.hair_model = r.string()
    v.blood = _bytes_list(r)
    if f.human_visual_dirt:
        v.dirt = _bytes_list(r)
    v.holes = _bytes_list(r)
    v.body_visuals = [read_item_visual(r, f) for _ in range(max(r.i8(), 0))]
    v.non_attached_hair = r.string()
    if f.human_visual_natural_colors:
        flags2 = r.u8()
        if flags2 & 4:
            v.natural_hair_color = _rgb(r)
        if flags2 & 2:
            v.natural_beard_color = _rgb(r)
    st.visual = v


def _inventory(r: ByteReader, st: PlayerState, ctx: DecodeContext, strict: bool) -> None:
    st.inventory = read_container(r, ctx)


def _sleep(r: ByteReader, st: PlayerState, ctx: DecodeContext, strict: bool) -> None:
    st.asleep = r.bool()
    st.force_wake_up_time = r.f32()


_PREFIX_SECTIONS: Tuple[Section, ...] = (
    ("header", _header),
    ("descriptor", _descriptor),
    ("visual", _visual),
    ("inventory", _inventory),
    ("sleep", _sleep),
)


# =============================================================================
# tail sections
# =============================================================================

def _plausible(cond: bool, what: str, r: ByteReader) -> None:
    if not cond:
        raise DecodeError(f"implausible {what}", r.pos)


def _stats(r: ByteReader, st: PlayerState, ctx: DecodeContext, strict: bool) -> None:
    f = ctx.features
    names = _STATS_V2 if f.stats_named else _STATS_V1 + (("stress_from_cigarettes",) if f.stats_cigarettes else ())
    stats = {}
    for name in names:
        v = r.f32()
        if strict:
            _plausible(math.isfinite(v) and -1e4 < v < 1e4, f"stat {name}={v}", r)
        stats[name] = v
    st.stats = stats


def _body_part(r: ByteReader, name: str, f: Features, strict: bool) -> BodyPart:
    p = BodyPart(name)
    if f.bodypart_cut:
        p.cut = r.bool()
    p.bitten, p.scratched, p.bandaged, p.bleeding = r.bool(), r.bool(), r.bool(), r.bool()
    p.deep_wounded, p.fake_infected, p.infected = r.bool(), r.bool(), r.bool()
    p.health = r.f32()
    if strict:
        _plausible(0.0 <= p.health <= 100.0, f"{name} health {p.health}", r)
    if f.bodypart_legacy_int:
        r.i32()
    if not f.bodypart_extended:
        return p
    if p.bandaged:
        p.bandage_life = r.f32()
    p.infected_wound = r.bool()
    if p.infected_wound:
        p.wound_infection_level = r.f32()
    if f.bodypart_cut:
        p.cut_time = r.f32()
    p.bite_time, p.scratch_time, p.bleeding_time = r.f32(), r.f32(), r.f32()
    p.alcohol_level, p.additional_pain, p.deep_wound_time = r.f32(), r.f32(), r.f32()
    p.have_glass, p.get_bandage_xp = r.bool(), r.bool()
    if f.bodypart_stitch:
        p.stitched = r.bool()
        p.stitch_time = r.f32()
    p.get_stitch_xp, p.get_splint_xp = r.bool(), r.bool()
    p.fracture_time = r.f32()
    p.splint = r.bool()
    if p.splint:
        p.splint_factor = r.f32()
    p.have_bullet = r.bool()
    p.burn_time = r.f32()
    p.need_burn_wash = r.bool()
    p.last_time_burn_wash = r.f32()
    p.splint_item = r.string()
    p.bandage_type = r.string()
    trailing_cut_time = r.f32()
    if not f.bodypart_cut:
        p.cut_time = trailing_cut_time
    if f.bodypart_wetness:
        p.wetness = r.f32()
    if f.bodypart_stiffness:
        p.stiffness = r.f32()
    if f.bodypart_herbal:
        p.herbal = {"comfrey": r.f32(), "garlic": r.f32(), "plantain": r.f32()}
    return p


def _typed(r: ByteReader, kind: str):
    return r.f32() if kind == "f" else r.bool() if kind == "b" else r.i32()


def _body(r: ByteReader, st: PlayerState, ctx: DecodeContext, strict: bool) -> None:
    f = ctx.features
    body = BodyDamage(parts=[_body_part(r, name, f, strict) for name in BODY_PARTS])
    for key, kind in (_BODY_MAIN_V2 if f.body_main_v2 else _BODY_MAIN_V1):
        if key == "time_to_sneeze_or_cough" and not f.body_sneeze:
            continue
        body.fields[key] = _typed(r, kind)
    if f.body_discomfort and not f.body_main_v2:
        body.fields["discomfort_level"] = r.f32()
    if f.thermoregulator and r.bool():
        body.thermoregulator = _thermoregulator(r, f)
    st.body = body


def _thermoregulator(r: ByteReader, f: Features) -> dict:
    # Build 42 at world version 249 stores 9 floats in the header and per node.
    # The first ones match the older layout; the rest are kept unnamed.
    header_names = _THERMO_V1 + (("unknown_7", "unknown_8") if f.thermoregulator_v2 else ())
    node_names = _THERMO_NODE_V1
    if f.thermoregulator_v2:
        node_names += ("insulation", "unknown_6", "unknown_7", "unknown_8")
    elif f.thermo_insulation:
        node_names += ("insulation",)
    thermo = {k: r.f32() for k in header_names}
    nodes = []
    for _ in range(r.count(limit=64, min_item_size=4 + 4 * len(node_names))):
        node = {"body_part": _part_name(r.i32())}
        node.update({k: r.f32() for k in node_names})
        nodes.append(node)
    thermo["nodes"] = nodes
    return thermo


def _part_name(index: int) -> str:
    return BODY_PARTS[index] if 0 <= index < len(BODY_PARTS) else f"#{index}"


def _skills(r: ByteReader, st: PlayerState, ctx: DecodeContext, strict: bool) -> None:
    f = ctx.features
    s = Skills()
    s.traits = [r.string() for _ in range(r.count(min_item_size=2))]
    s.total_xp = r.f32()
    s.level = r.i32()
    s.last_level = r.i32()
    for _ in range(r.count(min_item_size=6)):
        perk = _read_perk(r, f)
        s.xp[perk] = r.f32()
    if f.xp_legacy_list:
        for _ in range(r.count(min_item_size=2)):
            _read_perk(r, f)
    for _ in range(r.count(min_item_size=6)):
        perk = _read_perk(r, f)
        s.levels[perk] = r.i32()
    for _ in range(r.count(min_item_size=8)):
        perk = _read_perk(r, f)
        s.multipliers[perk] = {"multiplier": r.f32(), "min_level": r.i8(), "max_level": r.i8()}
    st.skills = s


def _character(r: ByteReader, st: PlayerState, ctx: DecodeContext, strict: bool) -> None:
    f = ctx.features
    st.left_hand_index = r.i32()
    st.right_hand_index = r.i32()
    st.on_fire = r.bool()
    st.effects = {k: r.f32() for k in _EFFECTS}
    books = {}
    for _ in range(r.count(min_item_size=6)):
        title = r.string()
        books[title] = r.i32()
    st.read_books = books
    st.reduce_infection_power = r.f32()
    st.known_recipes = [r.string() for _ in range(r.count(min_item_size=2))]
    st.last_hour_slept = r.i32()
    st.time_since_last_smoke = r.f32()
    st.beard_grow_timing = r.f32()
    st.hair_grow_timing = r.f32()
    cheats = {name: r.bool() for name in f.cheat_names()}
    st.sneaking = cheats.pop("sneaking", None)
    st.death_drag_down = cheats.pop("death_drag_down", None)
    st.cheats = cheats
    if f.read_literature:
        literature = {}
        for _ in range(r.count(min_item_size=6)):
            title = r.string()
            literature[title] = r.i32()
        st.read_literature = literature
    if f.read_print_media:
        st.read_print_media = [r.string() for _ in range(r.count(min_item_size=2))]
    if f.last_animal_pet:
        st.last_animal_pet = r.i64()
    if f.player_cheats:
        cheat_ids = [r.i8() for _ in range(r.count(min_item_size=1))]
        st.player_cheats = [PLAYER_CHEAT_TYPES[i] if 0 <= i < len(PLAYER_CHEAT_TYPES) else f"cheat#{i}"
                            for i in cheat_ids]


def _string_map(r: ByteReader, read_value: Callable[[], object], value_size: int) -> dict:
    out = {}
    for _ in range(r.count(min_item_size=2 + value_size)):
        key = r.string()
        out[key] = read_value()
    return out


def _player(r: ByteReader, st: PlayerState, ctx: DecodeContext, strict: bool) -> None:
    f = ctx.features
    st.hours_survived = r.f64()
    st.zombie_kills = r.i32()
    if strict:
        _plausible(math.isfinite(st.hours_survived) and 0 <= st.hours_survived < 1e7,
                   f"hours survived {st.hours_survived}", r)
        _plausible(st.zombie_kills >= 0, f"zombie kills {st.zombie_kills}", r)
    worn = []
    for _ in range(max(r.i8(), 0)):
        location = r.string()
        worn.append(WornItem(location=location, index=r.i16()))
    st.worn = worn
    st.primary_hand_index = r.i16()
    st.secondary_hand_index = r.i16()
    st.survivor_kills = r.i32()
    st.nutrition = Nutrition(r.f32(), r.f32(), r.f32(), r.f32(), r.f32())
    st.all_chat_muted = r.bool()
    st.tag_prefix = r.string()
    st.tag_color = (r.f32(), r.f32(), r.f32())
    st.display_name = r.string()
    st.show_tag = r.bool()
    st.faction_pvp = r.bool()
    if f.auto_drink:
        st.auto_drink = r.bool()
    if f.extra_info_flags:
        st.extra_info_flags = r.u8()
    elif f.no_clip:
        st.no_clip = r.bool()
    if r.bool():
        st.vehicle = VehicleSeat(x=r.f32(), y=r.f32(), seat=r.i8(), engine_running=r.bool())
    st.mechanics_items = {r.i64(): r.i64() for _ in range(r.count(min_item_size=16))}
    if f.fitness:
        fitness = {
            "stiffness_increase": _string_map(r, r.f32, 4),
            "stiffness_timer": _string_map(r, r.i32, 4),
            "regularity": _string_map(r, r.f32, 4),
            "body_parts_to_increase_stiffness": [r.string() for _ in range(r.count(min_item_size=2))],
        }
        if f.fitness_exe_timer:
            fitness["exercise_timer"] = _string_map(r, r.i64, 8)
        st.fitness = fitness
    if f.already_read_books == "ids":
        start = r.pos
        n = r.i16()
        if n < 0:
            raise DecodeError(f"negative read-book count {n}", start)
        st.already_read_books = [ctx.item_label(r.i16()) for _ in range(n)]
    elif f.already_read_books == "names":
        st.already_read_books = [r.string() for _ in range(r.count(min_item_size=2))]
    if f.known_media_lines:
        start = r.pos
        n = r.i16()
        if n < 0:
            raise DecodeError(f"negative media line count {n}", start)
        st.known_media_lines = [r.string() for _ in range(n)]
    if f.voice_type:
        st.voice_type = r.i8()
    if f.craft_history:
        history = []
        for _ in range(r.count(min_item_size=16)):
            start = r.pos
            n_chars = r.count(limit=4096, min_item_size=2)
            try:
                recipe = r.take(n_chars * 2).decode("utf-16-be")
            except UnicodeDecodeError as exc:
                raise DecodeError("invalid UTF-16 craft history key", start) from exc
            history.append({"recipe": recipe, "count": r.i32(), "last_craft_time": r.f64()})
        st.craft_history = history


_TAIL_SECTIONS: Tuple[Section, ...] = (
    ("stats", _stats),
    ("body", _body),
    ("skills", _skills),
    ("character", _character),
    ("player", _player),
)

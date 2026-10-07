"""Inventory decoding (``ItemContainer`` / ``InventoryItem`` and subclasses).

Each item is written with a 4-byte length prefix (``saveWithSize``), so the
decoder always knows where the next item starts.  That makes the inventory
robust against unknown or changed item formats: an item whose type-specific
part cannot be decoded keeps its common fields, gets ``undecoded`` set, and
the decoder carries on with the next item.

Build 42 stopped recording each item's type in the save (it writes -1), so
for those items the type is inferred: every type reader is tried and the one
that consumes the item's bytes exactly wins.

Type-specific readers are pluggable via :func:`register_item_reader`.
"""

from __future__ import annotations

import copy
from typing import Callable, Dict, List, Optional, Protocol, Tuple

from .binary import ByteReader, DecodeError, read_lua_table
from .state import Container, Item, ItemVisual
from .versions import Features

__all__ = ["ITEM_KINDS", "DecodeContext", "ItemNameResolver", "read_container", "read_item_visual",
           "register_item_reader"]

# zombie.scripting.objects.Item.Type, by ordinal (the item "save type" byte).
ITEM_KINDS: Tuple[str, ...] = (
    "Normal", "Weapon", "Food", "Literature", "Drainable", "Clothing", "Container",
    "WeaponPart", "Key", "KeyRing", "Moveable", "Radio", "AlarmClock",
    "AlarmClockClothing", "Map", "Animal",
)

_MAX_CONTAINER_DEPTH = 32


class ItemNameResolver(Protocol):
    def full_type(self, registry_id: int) -> Optional[str]: ...


class DecodeContext:
    """Per-decode settings shared by all readers."""

    def __init__(self, features: Features, names: Optional[ItemNameResolver] = None):
        self.features = features
        self.names = names

    def item_name(self, registry_id: int) -> Optional[str]:
        return self.names.full_type(registry_id) if self.names is not None else None

    def item_label(self, registry_id: int) -> str:
        return self.item_name(registry_id) or f"#{registry_id}"


class _Unsupported(Exception):
    """Data the decoder recognises but deliberately does not decode."""


ItemReader = Callable[[ByteReader, Item, DecodeContext, int], None]
_READERS: Dict[str, Tuple[ItemReader, bool]] = {}


def register_item_reader(kind: str, reader: ItemReader, *, allow_trailing: bool = False) -> None:
    """Install a reader for the type-specific part of items of ``kind``.

    The reader receives a :class:`ByteReader` limited to the item's own bytes,
    positioned right after the common ``InventoryItem`` fields.  Leftover bytes
    are reported in ``Item.undecoded`` unless ``allow_trailing`` is set.
    """
    _READERS[kind] = (reader, allow_trailing)


# -- helpers -----------------------------------------------------------------

def _unit(b: int) -> float:
    """``Bits.unpackByteToFloatUnit`` for a signed byte."""
    return round((b + 128) / 255.0, 4)


def _byte_list(r: ByteReader) -> List[int]:
    n = r.i8()
    return list(r.take(n)) if n > 0 else []


def _rgb(r: ByteReader) -> Tuple[int, int, int]:
    return (r.u8(), r.u8(), r.u8())


def read_item_visual(r: ByteReader, f: Features) -> ItemVisual:
    v = ItemVisual()
    flags = r.u8()
    if f.item_visual_full_type:
        v.full_type = r.string() or None
        v.alternate_model_name = r.string() or None
    v.clothing_item_name = r.string() or None
    if flags & 1:
        v.tint = _rgb(r)
    if flags & 2:
        v.base_texture = r.i8()
    if flags & 4:
        v.texture_choice = r.i8()
    if f.item_visual_hue_decal:
        if flags & 8:
            v.hue = r.f32()
        if flags & 16:
            v.decal = r.string()
    v.blood = _byte_list(r)
    if f.item_visual_dirt:
        v.dirt = _byte_list(r)
    v.holes = _byte_list(r)
    if f.item_visual_basic_patches:
        v.basic_patches = _byte_list(r)
    if f.item_visual_denim_leather:
        v.denim_patches = _byte_list(r)
        v.leather_patches = _byte_list(r)
    return v


# -- containers ----------------------------------------------------------------

def read_container(r: ByteReader, ctx: DecodeContext, depth: int = 0) -> Container:
    """``ItemContainer.save``: type, explored, items, looted flag, capacity."""
    if depth > _MAX_CONTAINER_DEPTH:
        raise DecodeError("containers nested too deeply", r.pos)
    c = Container(type=r.string())
    c.explored = r.bool()
    c.items = _read_item_list(r, ctx, depth)
    c.has_been_looted = r.bool()
    c.capacity = r.i32()
    return c


def _read_item_list(r: ByteReader, ctx: DecodeContext, depth: int) -> List[Item]:
    """``CompressIdenticalItems.save``: identical items are stored once with a count."""
    f = ctx.features
    start = r.pos
    n = r.i16()
    if n < 0:
        raise DecodeError(f"negative item count {n}", start)
    items = []
    for _ in range(n):
        count_at = r.pos
        if f.stack_count == "int":
            count = r.i32()
        elif f.stack_count == "short":
            count = r.i16()
        else:
            count = 1
        if count < 1 or count > 1_000_000:
            raise DecodeError(f"implausible stack size {count}", count_at)
        item = read_item(r, ctx, depth)
        item.count = count
        if f.stack_ids and count > 1:
            if (count - 1) * 4 > r.remaining:
                raise DecodeError("stack ids run past the end of the data", r.pos)
            item.stack_ids = [r.i32() for _ in range(count - 1)]
        items.append(item)
    return items


# -- items ----------------------------------------------------------------------

# Readers tried, in order, when an item does not record its kind (Build 42 writes
# -1 there).  Most constrained first: a container must parse as a whole nested
# inventory, while a key is just an int and a byte.
_INFERENCE_ORDER = ("Container", "Food", "Weapon", "Literature", "Clothing", "AlarmClockClothing",
                    "AlarmClock", "Key")


def read_item(r: ByteReader, ctx: DecodeContext, depth: int = 0) -> Item:
    start = r.pos
    size = r.i32()
    if size < 2 or size > r.remaining:
        raise DecodeError(f"invalid item size {size}", start)
    w = r.window(size)  # ``r`` is now positioned at the next item no matter what
    registry_id = w.i16()
    save_type = w.i8() if ctx.features.item_save_type else -1
    known_kind = 0 <= save_type < len(ITEM_KINDS)
    item = Item(registry_id=registry_id, kind=ITEM_KINDS[save_type] if known_kind else "Unknown",
                full_type=ctx.item_name(registry_id), encoded_size=size + 4)
    try:
        _read_common(w, item, ctx)
        if not known_kind:
            _infer_kind(w, item, ctx, depth)
        else:
            reader = _READERS.get(item.kind)
            if reader is not None:
                fn, allow_trailing = reader
                fn(w, item, ctx, depth)
                if not w.at_end() and not allow_trailing:
                    item.undecoded = f"{w.remaining} unexpected trailing bytes in {item.kind} data"
            elif not w.at_end():
                item.extra["type_specific_bytes"] = w.remaining
    except (_Unsupported, DecodeError) as exc:
        item.undecoded = str(exc)
    if item.full_type is None and item.visual is not None and item.visual.full_type:
        item.full_type = item.visual.full_type
    return item


def _infer_kind(w: ByteReader, item: Item, ctx: DecodeContext, depth: int) -> None:
    """Pick the item type whose reader consumes the remaining bytes exactly."""
    item.extra["kind_inferred"] = True
    if w.at_end():
        item.kind = "Normal"  # also drainables, weapon parts, key rings: nothing type-specific saved
        return
    order = list(_INFERENCE_ORDER)
    start = w.pos
    key_bytes = item.key_id.to_bytes(4, "big", signed=True) if item.key_id is not None else None
    if key_bytes is not None and w.remaining == 5 and w.data[start:start + 4] == key_bytes:
        order.remove("Key")
        order.insert(0, "Key")
    elif item.visual is not None and item.visual.clothing_item_name:
        order.remove("Clothing")
        order.insert(1, "Clothing")
    if item.visual is None:  # clothing always carries an ItemVisual; never guess it otherwise
        order = [k for k in order if k not in ("Clothing", "AlarmClockClothing")]
    for kind in order:
        fn, _ = _READERS[kind]
        trial = copy.copy(item)
        trial.details, trial.extra, trial.contents = {}, dict(item.extra), None
        tr = ByteReader(w.data, start, w.end)
        try:
            fn(tr, trial, ctx, depth)
        except (_Unsupported, DecodeError):
            continue
        if tr.at_end():
            item.__dict__.update(trial.__dict__)
            item.kind = kind
            w.pos = w.end
            return
    item.kind = "Unknown"
    item.extra["type_specific_bytes"] = w.remaining
    item.undecoded = (f"item type is not recorded and none of the known item layouts fits its "
                      f"{w.remaining} type-specific bytes")


def _check_flags(flags: int, known: int, what: str) -> None:
    unknown = flags & ~known
    if unknown:
        raise _Unsupported(f"unknown {what} flags 0x{unknown & 0xFFFFFFFF:x} (newer game version?)")


def _read_common(w: ByteReader, item: Item, ctx: DecodeContext) -> None:
    """``InventoryItem.load``: fields shared by every item type."""
    f = ctx.features
    item.id = w.i32()
    h = w.u8()
    if not h:
        return
    _check_flags(h, 0x7F, "item header")
    if h & 1:
        item.uses = w.i32() if f.item_uses_int else w.i16()
    if h & 2 and not f.item_uses_int:
        item.used_delta = _unit(w.i8())
    if h & 4:
        item.condition = w.i8()
    if h & 8:
        item.visual = read_item_visual(w, f)
    if h & 16:
        item.extra["color"] = tuple(_unit(w.i8()) for _ in range(4))
    if h & 32:
        item.extra["item_capacity"] = w.f32()
    if not h & 64:
        return

    g = w.i32()
    known = (1 << 26) - 1
    if f.item_b42_flags:
        known |= 0xF << 26
        if f.item_rotation_flag:
            known |= 1 << 30
    _check_flags(g, known, "item")
    if g & 1:
        item.mod_data = read_lua_table(w)
    item.activated = bool(g & 2)
    if g & 4:
        item.extra["have_been_repaired"] = w.i16()
    if g & 8:
        item.name = w.string()
    if g & 16:
        n = w.count(min_item_size=1)
        w.skip(n)
        item.extra["byte_data_size"] = n
    if g & 32:
        n = w.count(min_item_size=2)
        item.extra["extra_items"] = [ctx.item_label(w.i16()) for _ in range(n)]
    if g & 64:
        item.extra["custom_name"] = True
    if g & 128:
        weight = w.f32()
        if weight >= 0:
            item.extra["custom_weight"] = weight
    if g & 256:
        item.key_id = w.i32()
    if g & 512 and not f.item_b42_flags:
        item.extra["tainted_water"] = True
    if g & 1024:
        item.extra["remote_control_id"] = w.i32()
        item.extra["remote_range"] = w.i32()
    if g & 2048:
        item.extra["color_rgb"] = (_unit(w.i8()), _unit(w.i8()), _unit(w.i8()))
    if g & 4096:
        item.extra["worker"] = w.string()
    if g & 8192:
        item.extra["wet_cooldown"] = w.f32()
    item.favorite = bool(g & 16384)
    if g & 32768:
        item.extra["stash_map"] = w.string()
    item.infected = bool(g & 65536)
    if g & 131072:
        item.current_ammo_count = w.i32()
    if g & 262144:
        item.attached_slot = w.i32()
    if g & 524288:
        if f.item_attached_slot_type_str:
            item.attached_slot_type = w.string()
        else:
            w.i16()
    if g & 1048576:
        item.attached_to_model = w.string()
    if g & 2097152:
        item.extra["max_capacity"] = w.i32()
    if g & 4194304:
        item.extra["recorded_media_index"] = w.i16()
    if g & 8388608 and not f.item_rotation_floats:
        item.extra["world_z_rotation"] = w.i32()
    if g & 16777216:
        item.extra["world_scale"] = w.f32()
    if g & 33554432:
        item.extra["initialised"] = True
    if not f.item_b42_flags:
        return
    if g & 67108864:
        item.extra["components"] = _read_entity(w, item)
    if g & 134217728:
        raise _Unsupported("animal track data is not decoded")
    if g & 268435456:
        item.extra["texture"] = w.string()
    if g & 536870912:
        item.extra["model_index"] = w.i32()
    if g & 1073741824:
        if f.item_rotation_floats:
            item.extra["world_rotation"] = (w.f32(), w.f32(), w.f32())
        else:
            item.extra["world_rotation"] = (float(w.i32()), float(w.i32()))  # stored as Y, X


# -- crafting-entity components (Build 42) ------------------------------------------------

# zombie.entity.ComponentType ids.
COMPONENT_TYPES = {
    1: "Attributes", 2: "FluidContainer", 3: "SpriteConfig", 6: "Lua", 7: "Parts", 8: "Signals",
    9: "Script", 11: "UiConfig", 12: "CraftLogic", 13: "FurnaceLogic", 14: "TestComponent",
    15: "MashingLogic", 16: "DryingLogic", 17: "MetaTag", 18: "Resources", 19: "CraftBench",
    20: "CraftRecipe", 21: "Durability", 22: "DryingCraftLogic", 23: "ContextMenuConfig",
    24: "SpriteOverlayConfig", 25: "CraftBenchSounds", 26: "WallCoveringConfig",
}
# zombie.entity.components.fluids.FluidType ids.
FLUID_TYPES = {
    1: "Water", 2: "Petrol", 3: "Alcohol", 4: "TaintedWater", 5: "Beer", 6: "Whiskey", 7: "SodaPop",
    8: "Coffee", 9: "Tea", 10: "Wine", 11: "Bleach", 12: "Blood", 14: "Honey", 15: "Mead", 16: "Acid",
    17: "SpiffoJuice", 18: "SecretFlavoring", 19: "CarbonatedWater", 20: "CowMilk", 21: "SheepMilk",
    22: "CleaningLiquid", 23: "AnimalBlood", 24: "AnimalGrease", 64: "Dye", 65: "HairDye", 66: "Paint",
    70: "PoisonWeak", 71: "PoisonNormal", 72: "PoisonStrong", 73: "PoisonPotent", 74: "AnimalMilk",
    127: "Modded",
}


def _read_entity(w: ByteReader, item: Item) -> List[Dict[str, object]]:
    """``GameEntity.saveEntity``: a byte count, then length-framed components."""
    components = []
    for _ in range(max(w.i8(), 0)):
        length = w.count(limit=10_000_000, min_item_size=1)
        block = w.window(length)
        component_id = block.i16()
        comp: Dict[str, object] = {"type": COMPONENT_TYPES.get(component_id, f"component#{component_id}"),
                                   "size": length}
        if component_id == 2:
            try:
                comp.update(_read_fluid_container(block))
                item.details["fluids"] = comp["fluids"]
                if "capacity" in comp:
                    item.details["fluid_capacity"] = comp["capacity"]
            except DecodeError:
                comp["undecoded"] = True
        components.append(comp)
    return components


def _read_fluid_container(r: ByteReader) -> Dict[str, object]:
    h = r.u16()
    out: Dict[str, object] = {}
    if h & 1:
        out["capacity"] = r.f32()
    fluids = []
    if h & 2:
        for _ in range(1 if h & 4 else max(r.i8(), 0)):
            fh = r.u8()
            fluid: Dict[str, object] = {}
            if fh & 1:
                fid = r.i8()
                fluid["fluid"] = FLUID_TYPES.get(fid, f"fluid#{fid}")
            elif fh & 2:
                fluid["fluid"] = r.string()
            if fh & 4:
                fluid["color"] = (_unit(r.i8()), _unit(r.i8()), _unit(r.i8()))
            fluid["amount"] = r.f32()
            fluids.append(fluid)
    out["fluids"] = fluids
    return out  # filters and flags that follow are not needed


# -- type-specific readers -----------------------------------------------------------

def _read_container_item(w: ByteReader, item: Item, ctx: DecodeContext, depth: int) -> None:
    container_id = w.i32()
    weight_reduction = w.i32()
    item.contents = read_container(w, ctx, depth + 1)
    item.contents.id = container_id
    item.contents.weight_reduction = weight_reduction


def _read_clothing(w: ByteReader, item: Item, ctx: DecodeContext, depth: int) -> None:
    d = item.details
    h = w.u8()
    _check_flags(h, 0x3F, "clothing")
    if h & 1:
        d["sprite_name"] = w.string()
    if h & 2:
        d["dirtiness"] = w.finite_f32()
    if h & 4:
        d["blood_level"] = w.finite_f32()
    if h & 8:
        d["wetness"] = w.finite_f32()
    if h & 16:
        d["last_wetness_update"] = w.finite_f32()
    if h & 32:
        patches = []
        for _ in range(max(w.i8(), 0)):
            patches.append({
                "body_part": w.i8(),
                "tailor_level": w.i8(),
                "fabric_type": w.i16() if ctx.features.clothing_patch_fabric_short else w.i8(),
                "scratch_defense": w.i8(),
                "bite_defense": w.i8(),
                "has_hole": w.bool(),
                "condition_gain": w.i16(),
            })
        d["patches"] = patches


def _read_food(w: ByteReader, item: Item, ctx: DecodeContext, depth: int) -> None:
    f = ctx.features
    d = item.details
    d["age"] = w.finite_f32()
    d["last_aged"] = w.finite_f32()
    d.update(cooked=False, burnt=False, frozen=False, poison=False)
    h = w.u8()
    _check_flags(h, 0x7F, "food header")
    if h & 1:
        d["calories"], d["proteins"], d["lipids"], d["carbohydrates"] = (w.finite_f32() for _ in range(4))
    for bit, key in ((2, "hunger_change"), (4, "base_hunger"), (8, "unhappy_change"),
                     (16, "boredom_change"), (32, "thirst_change")):
        if h & bit:
            d[key] = w.finite_f32()
    if not h & 64:
        return
    g = w.i32()
    known = (1 << 26) - 1
    if f.food_animal_fields:
        known |= 3 << 26
    if f.food_stress_change:
        known |= 1 << 28
    _check_flags(g, known, "food")
    if g & 1:
        d["heat"] = w.f32()
    if g & 2:
        d["last_cook_minute"] = w.i32()
    if g & 4:
        d["cooking_time"] = w.f32()
    d["cooked"] = bool(g & 8)
    d["burnt"] = bool(g & 16)
    d["is_cookable"] = bool(g & 32)
    d["dangerous_uncooked"] = bool(g & 64)
    if g & 128:
        d["poison_detection_level"] = w.i8()
    if g & 256:
        d["spices"] = [w.string() for _ in range(max(w.i8(), 0))]
    if g & 512:
        d["poison_power"] = w.i8()
    if g & 1024:
        d["chef"] = w.string()
    if g & 2048:
        d["off_age"] = w.i32()
    if g & 4096:
        d["off_age_max"] = w.i32()
    if g & 8192:
        d["pain_reduction"] = w.f32()
    if g & 16384:
        d["flu_reduction"] = w.i32()
    if g & 32768:
        d["reduce_food_sickness"] = w.i32()
    d["poison"] = bool(g & 65536)
    if g & 131072:
        d["use_for_poison"] = w.i16()
    if g & 262144:
        d["freezing_time"] = w.f32()
    d["frozen"] = bool(g & 524288)
    if g & 1048576:
        d["last_frozen_update"] = w.f32()
    if g & 2097152:
        d["rotten_time"] = w.f32()
    if g & 4194304:
        d["compost_time"] = w.f32()
    d["cooked_in_microwave"] = bool(g & 8388608)
    if g & 16777216:
        d["fatigue_change"] = w.f32()
    if g & 33554432:
        d["endurance_change"] = w.f32()
    if g & 67108864:
        d["milk_quantity"] = w.i32()
        d["milk_type"] = w.string()
    if g & 134217728:
        raise _Unsupported("fertilized egg genome data is not decoded")
    if g & 268435456:
        d["stress_change"] = w.f32()


_WEAPON_SLOTS = ((1024, "scope"), (2048, "clip"), (4096, "recoil_pad"),
                 (8192, "sling"), (16384, "stock"), (32768, "canon"))


def _read_weapon(w: ByteReader, item: Item, ctx: DecodeContext, depth: int) -> None:
    f = ctx.features
    d = item.details
    h = w.i32()
    known = 0x3FF | (0x7F << 16)  # 1..512 and 65536..4194304
    if not f.weapon_attachment_list:
        known |= 0x3F << 10
    else:
        known |= 0x7 << 23
        if f.weapon_b42_extras:
            known |= 0x7 << 10
    _check_flags(h, known, "weapon")
    for bit, key, kind in ((1, "max_range", "f"), (2, "min_range_ranged", "f"), (4, "clip_size", "i"),
                           (8, "min_damage", "f"), (16, "max_damage", "f"), (32, "recoil_delay", "i"),
                           (64, "aiming_time", "i"), (128, "reload_time", "i"), (256, "hit_chance", "i"),
                           (512, "min_angle", "f")):
        if h & bit:
            d[key] = w.finite_f32() if kind == "f" else w.i32()
    attachments: Dict[str, str] = {}
    if not f.weapon_attachment_list:
        for bit, slot in _WEAPON_SLOTS:
            if h & bit:
                attachments[slot] = ctx.item_label(w.i16())
    elif f.weapon_b42_extras:
        if h & 1024:  # attached weapon parts, saved without a size prefix
            for i in range(max(w.i8(), 0)):
                part = Item(registry_id=w.i16(), kind="WeaponPart")
                part.full_type = ctx.item_name(part.registry_id)
                w.i8()
                _read_common(w, part, ctx)
                attachments[f"part_{i}"] = part.display_name
        if h & 2048:
            d["fire_mode"] = w.string()
        if h & 4096:
            d["cyclic_rate_multiplier"] = w.finite_f32()
    if h & 65536:
        d["explosion_timer"] = w.i32()
    if h & 131072:
        d["max_angle"] = w.f32()
    if h & 262144:
        d["blood_level"] = w.f32()
    d["contains_clip"] = bool(h & 524288)
    d["round_chambered"] = bool(h & 1048576)
    d["jammed"] = bool(h & 2097152)
    if h & 4194304:
        d["weapon_sprite"] = w.string()
    if f.weapon_attachment_list:
        if h & 8388608:
            d["min_sight_range"] = w.f32()
        if h & 16777216:
            d["max_sight_range"] = w.f32()
        if h & 33554432:
            for i in range(max(w.i8(), 0)):
                attachments[f"slot_{i}"] = ctx.item_label(w.i16())
    if attachments:
        d["attachments"] = attachments


def _read_literature(w: ByteReader, item: Item, ctx: DecodeContext, depth: int) -> None:
    d = item.details
    short_header = ctx.features.literature_short_header
    h = w.u16() if short_header else w.u8()
    _check_flags(h, 0xFF if short_header else 0x7F, "literature")
    width = 1
    if h & 1:
        if h & 2:
            width = 2
        elif h & 4:
            width = 4
    read_n = {1: w.i8, 2: w.i16, 4: w.i32}[width]
    if h & 1:
        d["number_of_pages"] = read_n()
    if h & 8:
        d["already_read_pages"] = read_n()
    d["can_be_written"] = bool(h & 16)
    if h & 32:
        n = w.i32()
        d["custom_pages"] = [w.string() for _ in range(max(n, 0))]
    if h & 64:
        d["locked_by"] = w.string()
    if h & 128:
        d["learned_recipes"] = [w.string() for _ in range(max(w.i16(), 0))]


def _read_key(w: ByteReader, item: Item, ctx: DecodeContext, depth: int) -> None:
    item.key_id = w.i32()
    item.details["number_of_keys"] = w.i8()


def _read_alarm(w: ByteReader, item: Item, ctx: DecodeContext, depth: int) -> None:
    d = item.details
    hour, minutes = w.i32(), w.i32()
    if not (-1 <= hour <= 23 and -1 <= minutes <= 59):
        raise DecodeError(f"implausible alarm time {hour}:{minutes}", w.pos)
    d["alarm_time"] = f"{hour:02d}:{minutes:02d}" if hour >= 0 and minutes >= 0 else None
    d["alarm_set"] = w.bool()
    d["ring_since"] = w.finite_f32()
    if ctx.features.alarm_force_dont_ring:
        d["force_dont_ring"] = w.i32()


def _read_alarm_clock_clothing(w: ByteReader, item: Item, ctx: DecodeContext, depth: int) -> None:
    _read_clothing(w, item, ctx, depth)
    _read_alarm(w, item, ctx, depth)


register_item_reader("Container", _read_container_item)
register_item_reader("Clothing", _read_clothing)
register_item_reader("AlarmClock", _read_alarm)
register_item_reader("AlarmClockClothing", _read_alarm_clock_clothing)
register_item_reader("Food", _read_food)
register_item_reader("Weapon", _read_weapon)
register_item_reader("Literature", _read_literature)
register_item_reader("Key", _read_key)

"""Save-format versioning.

Every player blob is stored next to the ``worldversion`` the game was running
when it wrote it.  The format changes with that number, so the decoder never
hard-codes a layout: it asks this module for a :class:`Features` set, a flat
list of switches describing which fields exist and how they are encoded.

Where the switches come from (newest game loader wins, because that is how
the game itself reads an older save):

* **Build 41** (world version <= 195): version checks in the decompiled
  ``load()`` methods of 41.78.16.
* **Build 42.0** (196..219): version checks in the decompiled 42.0 source.
* **Build 42, world version 220..241**: version checks in a decompile of a
  build writing world version 241.  A few structural changes (named stats,
  the body-part ``cut`` flag, slimmer ``BodyDamage`` fields) carry no version
  check there, so for 220..240 those are additionally *probed*.
* **World version 249**: a community reverse-engineering, confirmed on real
  249 save data.  The only known difference to 241 (the Thermoregulator
  layout) is probed for 242..248.
* **Anything newer**: the newest known layout first, then probing of every
  tail switch, and finally a partial decode (see :mod:`zomboid_db_api.decoder`).

Probing means trying the combinations of the uncertain switches and keeping
the one that consumes the blob exactly, byte for byte.

If you learn the layout of a new version you can teach the library without
changing it::

    from zomboid_db_api import versions
    versions.register_layout(260, 270, craft_history=True, player_cheats=True)
"""

from __future__ import annotations

import dataclasses
import itertools
from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple

__all__ = [
    "B41_WORLD_VERSION",
    "B42_FIRST_WORLD_VERSION",
    "B42_0_WORLD_VERSION",
    "B42_241_WORLD_VERSION",
    "B42_LATE_WORLD_VERSION",
    "Features",
    "LayoutPlan",
    "TAIL_FEATURES",
    "build_name",
    "features_for",
    "plan_for",
    "register_layout",
    "clear_registered_layouts",
]

B41_WORLD_VERSION = 195          # 41.78.x
B42_FIRST_WORLD_VERSION = 196    # first world version that only Build 42 writes
B42_0_WORLD_VERSION = 219        # 42.0.x (decompiled reference)
B42_241_WORLD_VERSION = 241      # later 42.x (decompiled reference)
B42_LATE_WORLD_VERSION = 249     # newest layout known field-by-field (verified on real saves)

_B41_CHEATS_OLD = ("unlimited_carry", "build", "health", "mechanics")


@dataclass(frozen=True)
class Features:
    """Switches describing one concrete blob layout.

    Most names map 1:1 to a ``if (worldVersion >= N)`` branch in the game's
    loaders; the comment on each says where it applies.
    """

    world_version: int
    family: str  # "B41" or "B42"

    # -- inventory items ------------------------------------------------------
    item_save_type: bool = True              # >= 70: item kind byte after registry id
    item_kind_recorded: bool = True          # < 220: that byte holds the kind (later: always -1)
    stack_count: str = "int"                 # >= 149 "int", >= 128 "short", else "none"
    stack_ids: bool = True                   # >= 128: ids of the other stacked copies
    item_uses_int: bool = False              # >= 220: uses is an int, no used-delta byte
    item_attached_slot_type_str: bool = True  # >= 179: attachedSlotType is a string
    item_b42_flags: bool = False             # B42: entity/animal tracks/texture/model flags
    item_rotation_flag: bool = False         # >= 220: world X/Y(/Z) rotation flag
    item_rotation_floats: bool = False       # >= 232: rotation as 3 floats (else 2 ints + Z int)
    weapon_attachment_list: bool = False     # B42: weapon parts saved as a list
    weapon_b42_extras: bool = False          # >= 220: nested parts, fire mode, cyclic rate
    food_animal_fields: bool = False         # B42: milk / fertilized egg data on food
    food_stress_change: bool = False         # >= 220
    literature_short_header: bool = False    # >= 226: 16-bit header + learned recipes
    alarm_force_dont_ring: bool = False      # >= 205
    clothing_patch_fabric_short: bool = False  # < 178: patch fabric type is a short

    # -- visuals ------------------------------------------------------------
    item_visual_full_type: bool = True       # >= 164
    item_visual_hue_decal: bool = True       # >= 146
    item_visual_dirt: bool = True            # >= 163
    item_visual_basic_patches: bool = True   # >= 154
    item_visual_denim_leather: bool = True   # >= 155
    human_visual_rot_stage: bool = True      # >= 156
    human_visual_dirt: bool = True           # >= 163
    human_visual_natural_colors: bool = True  # >= 187

    # -- descriptor / skills ------------------------------------------------------
    descriptor_voice: bool = False           # >= 208
    perks_as_strings: bool = True            # >= 152 (older: enum index)
    xp_legacy_list: bool = False             # < 162: an obsolete perk list in XP

    # -- stats and body -------------------------------------------------------
    stats_cigarettes: bool = True            # >= 97
    stats_named: bool = False                # >= 220: 24 named stats
    bodypart_legacy_int: bool = False        # 37..43: an unused int per body part
    bodypart_extended: bool = True           # >= 44
    bodypart_stitch: bool = True             # >= 48
    bodypart_wetness: bool = True            # >= 153
    bodypart_stiffness: bool = True          # >= 167
    bodypart_cut: bool = False               # >= 220: explicit cut flag + timer
    bodypart_herbal: bool = False            # >= 227: comfrey/garlic/plantain
    body_main_v2: bool = False               # >= 220: slimmer BodyDamage main fields
    body_sneeze: bool = False                # >= 222 (v2 main fields only)
    body_discomfort: bool = False            # 211..219 (pre-v2 main fields only)
    thermoregulator: bool = True             # >= 153
    thermo_insulation: bool = False          # >= 241: insulation per node
    thermoregulator_v2: bool = False         # 249: 9 floats per header/node

    # -- character tail -----------------------------------------------------
    read_literature: bool = False            # B42
    read_print_media: bool = False           # >= 222
    last_animal_pet: bool = False            # B42
    player_cheats: bool = False              # >= 231

    # -- player tail --------------------------------------------------------
    auto_drink: bool = False                 # >= 239
    no_clip: bool = True                     # >= 176 (B41)
    extra_info_flags: bool = False           # >= 198: replaces no_clip byte
    fitness: bool = True                     # >= 167
    fitness_exe_timer: bool = True           # >= 169
    already_read_books: str = "ids"          # >= 184 "ids", >= 182 "names", else "none"
    known_media_lines: bool = True           # >= 189
    voice_type: bool = False                 # >= 203
    craft_history: bool = False              # >= 228

    def cheat_names(self) -> Tuple[str, ...]:
        """Names of the cheat/state booleans after ``hairGrowTiming``, in order."""
        wv = self.world_version
        names = list(_B41_CHEATS_OLD)
        if self.family == "B42":
            names += ["movables", "farming"]
            if wv >= 202:
                names.append("fishing")
            if wv >= 217:
                names += ["can_use_brush_tool", "fast_move"]
            names += ["timed_action_instant", "unlimited_endurance"]
            if wv >= 230:
                names += ["unlimited_ammo", "know_all_recipes"]
            names += ["sneaking", "death_drag_down"]
        else:
            if wv >= 176:
                names += ["movables", "farming", "timed_action_instant", "unlimited_endurance"]
            if wv >= 161:
                names += ["sneaking", "death_drag_down"]
        return tuple(names)

    def replace(self, **changes) -> "Features":
        return dataclasses.replace(self, **changes)

    def differences(self, other: "Features") -> dict:
        return {f.name: getattr(self, f.name) for f in dataclasses.fields(self)
                if getattr(self, f.name) != getattr(other, f.name)}


# Switches that only affect the part of the blob after the inventory
# (Stats onwards).  These are the ones that may be probed, because the decoder
# parses the prefix once and re-runs only the tail per candidate.
TAIL_FEATURES: Tuple[str, ...] = (
    "stats_named",
    "body_main_v2",
    "bodypart_cut",
    "body_sneeze",
    "bodypart_herbal",
    "thermo_insulation",
    "thermoregulator_v2",
    "read_print_media",
    "player_cheats",
    "auto_drink",
    "craft_history",
)

# Changes the 241 loader applies without a version check.
_UNGATED_220 = ("stats_named", "body_main_v2", "bodypart_cut")


def build_name(world_version: int) -> str:
    if world_version <= B41_WORLD_VERSION:
        return "Build 41"
    return "Build 42"


def features_for(world_version: int) -> Features:
    """Features implied by the version checks alone (no probing)."""
    wv = int(world_version)
    b42 = wv >= B42_FIRST_WORLD_VERSION
    return Features(
        world_version=wv,
        family="B42" if b42 else "B41",
        item_save_type=wv >= 70,
        item_kind_recorded=wv < 220,
        stack_count="int" if wv >= 149 else "short" if wv >= 128 else "none",
        stack_ids=wv >= 128,
        item_uses_int=wv >= 220,
        item_attached_slot_type_str=wv >= 179,
        item_b42_flags=b42,
        item_rotation_flag=wv >= 220,
        item_rotation_floats=wv >= 232,
        weapon_attachment_list=b42,
        weapon_b42_extras=wv >= 220,
        food_animal_fields=b42,
        food_stress_change=wv >= 220,
        literature_short_header=wv >= 226,
        alarm_force_dont_ring=wv >= 205,
        clothing_patch_fabric_short=wv < 178,
        item_visual_full_type=wv >= 164,
        item_visual_hue_decal=wv >= 146,
        item_visual_dirt=wv >= 163,
        item_visual_basic_patches=wv >= 154,
        item_visual_denim_leather=wv >= 155,
        human_visual_rot_stage=wv >= 156,
        human_visual_dirt=wv >= 163,
        human_visual_natural_colors=wv >= 187,
        descriptor_voice=wv >= 208,
        perks_as_strings=wv >= 152,
        xp_legacy_list=wv < 162,
        stats_cigarettes=wv >= 97,
        stats_named=wv >= 220,
        bodypart_legacy_int=37 <= wv <= 43,
        bodypart_extended=wv >= 44,
        bodypart_stitch=wv >= 48,
        bodypart_wetness=wv >= 153,
        bodypart_stiffness=wv >= 167,
        bodypart_cut=wv >= 220,
        bodypart_herbal=wv >= 227,
        body_main_v2=wv >= 220,
        body_sneeze=wv >= 222,
        body_discomfort=211 <= wv < 220,
        thermoregulator=wv >= 153,
        thermo_insulation=wv >= B42_241_WORLD_VERSION,
        thermoregulator_v2=wv >= B42_LATE_WORLD_VERSION,
        read_literature=b42,
        read_print_media=wv >= 222,
        last_animal_pet=b42,
        player_cheats=wv >= 231,
        auto_drink=wv >= 239,
        no_clip=wv >= 176,
        extra_info_flags=wv >= 198,
        fitness=wv >= 167,
        fitness_exe_timer=wv >= 169,
        already_read_books="ids" if wv >= 184 else "names" if wv >= 182 else "none",
        known_media_lines=wv >= 189,
        voice_type=wv >= 203,
        craft_history=wv >= 228,
    )


@dataclass(frozen=True)
class LayoutPlan:
    """How to decode one world version: a primary layout plus switches to probe."""

    world_version: int
    primary: Features
    probe: Tuple[str, ...] = ()
    confidence: str = "exact"   # exact | gated | probed | extrapolated | legacy | custom
    note: str = ""

    def candidates(self) -> Iterator[Features]:
        """Primary layout first, then variants ordered by how many switches differ."""
        yield self.primary
        for flips in range(1, len(self.probe) + 1):
            for combo in itertools.combinations(self.probe, flips):
                yield self.primary.replace(**{name: not getattr(self.primary, name) for name in combo})


@dataclass(frozen=True)
class _Registration:
    min_version: int
    max_version: Optional[int]
    overrides: Tuple[Tuple[str, object], ...]
    probe: Tuple[str, ...]
    note: str

    def covers(self, wv: int) -> bool:
        return wv >= self.min_version and (self.max_version is None or wv <= self.max_version)


_registry: List[_Registration] = []


def register_layout(min_version: int, max_version: Optional[int] = None, *,
                    probe: Tuple[str, ...] = (), note: str = "", **overrides) -> None:
    """Declare the layout of a world-version range.

    ``overrides`` are :class:`Features` field values applied on top of the
    version checks; ``probe`` lists tail switches that are still uncertain.
    Later registrations win over earlier ones.
    """
    known = {f.name for f in dataclasses.fields(Features)}
    unknown = set(overrides) - known
    if unknown:
        raise ValueError(f"unknown feature switch(es): {', '.join(sorted(unknown))}")
    bad_probe = set(probe) - set(TAIL_FEATURES)
    if bad_probe:
        raise ValueError(f"only tail features can be probed, not: {', '.join(sorted(bad_probe))}")
    _registry.append(_Registration(min_version, max_version, tuple(overrides.items()), tuple(probe), note))


def clear_registered_layouts() -> None:
    _registry.clear()


def plan_for(world_version: int) -> LayoutPlan:
    wv = int(world_version)
    for reg in reversed(_registry):
        if reg.covers(wv):
            primary = features_for(wv).replace(**dict(reg.overrides))
            return LayoutPlan(wv, primary, reg.probe, "custom", reg.note or "registered layout")

    base = features_for(wv)
    if wv in (B41_WORLD_VERSION, B42_0_WORLD_VERSION, B42_241_WORLD_VERSION):
        return LayoutPlan(wv, base, (), "exact", "matches decompiled game source")
    if wv == B42_LATE_WORLD_VERSION:
        return LayoutPlan(wv, base, TAIL_FEATURES, "exact", "matches the known 249 layout (verified on real saves)")
    if wv < 152:
        return LayoutPlan(wv, base, (), "legacy", "very old save; perks are stored as enum indices")
    if wv < 220:
        return LayoutPlan(wv, base, (), "gated", "derived from version checks in the game source")
    if wv < B42_241_WORLD_VERSION:
        return LayoutPlan(wv, base, _UNGATED_220, "gated",
                          "version checks from the 241 source; changes it applies unconditionally are probed")
    if wv < B42_LATE_WORLD_VERSION:
        return LayoutPlan(wv, base, ("thermoregulator_v2",), "gated",
                          "between the known 241 and 249 layouts; the Thermoregulator layout is probed")
    return LayoutPlan(wv, base, TAIL_FEATURES, "extrapolated",
                      f"newer than the newest known layout ({B42_LATE_WORLD_VERSION})")

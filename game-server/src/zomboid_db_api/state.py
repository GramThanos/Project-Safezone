"""Data classes produced by the player blob decoder."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple

__all__ = [
    "RGB",
    "Descriptor",
    "ItemVisual",
    "HumanVisual",
    "Item",
    "Container",
    "BodyPart",
    "BodyDamage",
    "Skills",
    "Nutrition",
    "VehicleSeat",
    "WornItem",
    "PlayerState",
]

RGB = Tuple[int, int, int]


@dataclass
class Descriptor:
    """``SurvivorDesc``: who the character is."""

    id: int
    forename: str
    surname: str
    torso: str
    female: bool
    profession: str
    extras: List[str] = field(default_factory=list)
    xp_boosts: Dict[str, int] = field(default_factory=dict)
    voice_prefix: Optional[str] = None
    voice_pitch: Optional[float] = None
    voice_type: Optional[int] = None

    @property
    def full_name(self) -> str:
        return f"{self.forename} {self.surname}".strip()


@dataclass
class ItemVisual:
    full_type: Optional[str] = None
    alternate_model_name: Optional[str] = None
    clothing_item_name: Optional[str] = None
    tint: Optional[RGB] = None
    base_texture: Optional[int] = None
    texture_choice: Optional[int] = None
    hue: Optional[float] = None
    decal: Optional[str] = None
    blood: List[int] = field(default_factory=list)
    dirt: List[int] = field(default_factory=list)
    holes: List[int] = field(default_factory=list)
    basic_patches: List[int] = field(default_factory=list)
    denim_patches: List[int] = field(default_factory=list)
    leather_patches: List[int] = field(default_factory=list)


@dataclass
class HumanVisual:
    hair_color: Optional[RGB] = None
    beard_color: Optional[RGB] = None
    skin_color: Optional[RGB] = None
    body_hair: int = 0
    skin_texture: int = 0
    zombie_rot_stage: int = 0
    skin_texture_name: Optional[str] = None
    beard_model: Optional[str] = None
    hair_model: Optional[str] = None
    blood: List[int] = field(default_factory=list)
    dirt: List[int] = field(default_factory=list)
    holes: List[int] = field(default_factory=list)
    body_visuals: List[ItemVisual] = field(default_factory=list)
    non_attached_hair: str = ""
    natural_hair_color: Optional[RGB] = None
    natural_beard_color: Optional[RGB] = None


@dataclass
class Item:
    """One inventory entry.  Identical items are stacked: see ``count``."""

    registry_id: int
    kind: str
    full_type: Optional[str] = None
    id: Optional[int] = None
    count: int = 1
    stack_ids: List[int] = field(default_factory=list)
    uses: int = 1
    used_delta: Optional[float] = None
    condition: Optional[int] = None  # None: at maximum condition
    name: Optional[str] = None       # custom (player given) name
    favorite: bool = False
    infected: bool = False
    activated: bool = False
    key_id: Optional[int] = None
    current_ammo_count: int = 0
    attached_slot: Optional[int] = None
    attached_slot_type: Optional[str] = None
    attached_to_model: Optional[str] = None
    visual: Optional[ItemVisual] = None
    mod_data: Optional[Dict[Any, Any]] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    details: Dict[str, Any] = field(default_factory=dict)
    contents: Optional["Container"] = None
    encoded_size: int = 0
    undecoded: Optional[str] = None  # why (part of) this item could not be decoded

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name
        if self.full_type:
            return self.full_type
        return f"<item #{self.registry_id}>"


@dataclass
class Container:
    type: str
    explored: bool = False
    items: List[Item] = field(default_factory=list)
    has_been_looted: bool = False
    capacity: int = 0
    id: Optional[int] = None
    weight_reduction: Optional[int] = None

    def flat(self) -> List[Item]:
        """Items expanded by stack count, in save order.

        Worn-item and hand indices in the player blob point into this list.
        """
        out: List[Item] = []
        for item in self.items:
            out.extend([item] * max(item.count, 1))
        return out

    def walk(self, _depth: int = 0) -> Iterator[Tuple[int, Item]]:
        """Yield ``(depth, item)`` for every item, descending into bags."""
        for item in self.items:
            yield _depth, item
            if item.contents is not None:
                yield from item.contents.walk(_depth + 1)

    def total_count(self) -> int:
        return sum(item.count for _, item in self.walk())


@dataclass
class BodyPart:
    name: str
    health: float = 100.0
    bitten: bool = False
    scratched: bool = False
    cut: Optional[bool] = None
    bandaged: bool = False
    bleeding: bool = False
    deep_wounded: bool = False
    fake_infected: bool = False
    infected: bool = False
    bandage_life: Optional[float] = None
    infected_wound: bool = False
    wound_infection_level: Optional[float] = None
    bite_time: float = 0.0
    scratch_time: float = 0.0
    cut_time: float = 0.0
    bleeding_time: float = 0.0
    alcohol_level: float = 0.0
    additional_pain: float = 0.0
    deep_wound_time: float = 0.0
    have_glass: bool = False
    get_bandage_xp: bool = False
    stitched: bool = False
    stitch_time: float = 0.0
    get_stitch_xp: bool = False
    get_splint_xp: bool = False
    fracture_time: float = 0.0
    splint: bool = False
    splint_factor: Optional[float] = None
    have_bullet: bool = False
    burn_time: float = 0.0
    need_burn_wash: bool = False
    last_time_burn_wash: float = 0.0
    splint_item: str = ""
    bandage_type: str = ""
    wetness: float = 0.0
    stiffness: float = 0.0
    herbal: Optional[Dict[str, float]] = None

    _json_properties = ("conditions",)

    @property
    def conditions(self) -> List[str]:
        """Human readable list of what is wrong with (or applied to) this part."""
        out = []
        for flag, label in (("bitten", "bitten"), ("scratched", "scratched"), ("cut", "laceration"),
                            ("deep_wounded", "deep wound"), ("bleeding", "bleeding"),
                            ("infected", "zombie infection"), ("infected_wound", "infected wound"),
                            ("have_glass", "glass shard"), ("have_bullet", "bullet lodged"),
                            ("bandaged", "bandaged"), ("stitched", "stitched"), ("splint", "splint")):
            if getattr(self, flag):
                out.append(label)
        if self.fracture_time > 0:
            out.append("fracture")
        if self.burn_time > 0:
            out.append("burn")
        return out

    @property
    def is_injured(self) -> bool:
        return self.health < 100.0 or any(
            c not in ("bandaged", "stitched", "splint") for c in self.conditions)


@dataclass
class BodyDamage:
    parts: List[BodyPart] = field(default_factory=list)
    fields: Dict[str, Any] = field(default_factory=dict)
    thermoregulator: Optional[Dict[str, Any]] = None

    def part(self, name: str) -> BodyPart:
        for p in self.parts:
            if p.name.lower() == name.lower():
                return p
        raise KeyError(name)

    def injured_parts(self) -> List[BodyPart]:
        return [p for p in self.parts if p.is_injured]


@dataclass
class Skills:
    traits: List[str] = field(default_factory=list)
    total_xp: float = 0.0
    level: int = 0
    last_level: int = 0
    xp: Dict[str, float] = field(default_factory=dict)
    levels: Dict[str, int] = field(default_factory=dict)
    multipliers: Dict[str, Dict[str, float]] = field(default_factory=dict)


@dataclass
class Nutrition:
    calories: float
    proteins: float
    lipids: float
    carbohydrates: float
    weight: float


@dataclass
class VehicleSeat:
    x: float
    y: float
    seat: int
    engine_running: bool


@dataclass
class WornItem:
    location: str
    index: int
    item: Optional[Item] = None


@dataclass
class PlayerState:
    """Everything decoded from one ``networkPlayers``/``localPlayers`` blob.

    Decoding is best-effort and never raises on bad data: sections that could
    not be read are left at their defaults, ``complete`` is False and
    ``errors`` explains what happened.
    """

    world_version: int
    blob_size: int
    layout: str = ""
    confidence: str = ""
    complete: bool = False
    bytes_decoded: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    recovered_tail: bool = False
    stats_offset: Optional[int] = None

    # IsoMovingObject
    class_id: Optional[int] = None
    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None
    offset_x: Optional[float] = None
    offset_y: Optional[float] = None
    direction: Optional[str] = None
    mod_data: Optional[Dict[Any, Any]] = None

    # IsoGameCharacter
    descriptor: Optional[Descriptor] = None
    visual: Optional[HumanVisual] = None
    inventory: Optional[Container] = None
    asleep: Optional[bool] = None
    force_wake_up_time: Optional[float] = None
    stats: Dict[str, float] = field(default_factory=dict)
    body: Optional[BodyDamage] = None
    skills: Optional[Skills] = None
    left_hand_index: Optional[int] = None
    right_hand_index: Optional[int] = None
    on_fire: Optional[bool] = None
    effects: Dict[str, float] = field(default_factory=dict)
    read_books: Dict[str, int] = field(default_factory=dict)
    reduce_infection_power: Optional[float] = None
    known_recipes: List[str] = field(default_factory=list)
    last_hour_slept: Optional[int] = None
    time_since_last_smoke: Optional[float] = None
    beard_grow_timing: Optional[float] = None
    hair_grow_timing: Optional[float] = None
    cheats: Dict[str, bool] = field(default_factory=dict)
    sneaking: Optional[bool] = None
    death_drag_down: Optional[bool] = None
    read_literature: Dict[str, int] = field(default_factory=dict)
    read_print_media: List[str] = field(default_factory=list)
    last_animal_pet: Optional[int] = None
    player_cheats: List[str] = field(default_factory=list)

    # IsoPlayer
    hours_survived: Optional[float] = None
    zombie_kills: Optional[int] = None
    worn: List[WornItem] = field(default_factory=list)
    primary_hand_index: Optional[int] = None
    secondary_hand_index: Optional[int] = None
    survivor_kills: Optional[int] = None
    nutrition: Optional[Nutrition] = None
    all_chat_muted: Optional[bool] = None
    tag_prefix: Optional[str] = None
    tag_color: Optional[Tuple[float, float, float]] = None
    display_name: Optional[str] = None
    show_tag: Optional[bool] = None
    faction_pvp: Optional[bool] = None
    auto_drink: Optional[bool] = None
    no_clip: Optional[bool] = None
    extra_info_flags: Optional[int] = None
    vehicle: Optional[VehicleSeat] = None
    mechanics_items: Dict[int, int] = field(default_factory=dict)
    fitness: Dict[str, Any] = field(default_factory=dict)
    already_read_books: List[str] = field(default_factory=list)
    known_media_lines: List[str] = field(default_factory=list)
    voice_type: Optional[int] = None
    craft_history: List[Dict[str, Any]] = field(default_factory=list)

    # -- convenience --------------------------------------------------------
    @property
    def full_name(self) -> Optional[str]:
        return self.descriptor.full_name if self.descriptor else None

    @property
    def days_survived(self) -> Optional[float]:
        return None if self.hours_survived is None else self.hours_survived / 24.0

    def _inventory_item(self, index: Optional[int]) -> Optional[Item]:
        if index is None or index < 0 or self.inventory is None:
            return None
        flat = self.inventory.flat()
        return flat[index] if index < len(flat) else None

    @property
    def primary_hand(self) -> Optional[Item]:
        return self._inventory_item(self.primary_hand_index)

    @property
    def secondary_hand(self) -> Optional[Item]:
        return self._inventory_item(self.secondary_hand_index)

    @property
    def is_zombie_infected(self) -> Optional[bool]:
        """True when the zombie virus is in the character (bite, or knox infection)."""
        if self.body is None and not self.stats:
            return None
        if self.body is not None:
            if any(p.infected for p in self.body.parts):
                return True
            if (self.body.fields.get("infection_level") or 0) > 0:
                return True
        return (self.stats.get("zombie_infection") or 0) > 0

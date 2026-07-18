import re
from enum import Enum
from pydantic import BaseModel, Field, field_validator, model_validator

class Faction(str, Enum):
    DRACONIAN = "Draconian"
    DRUIDIAN = "Druidian"
    NECROMANCER = "Necromancer"
    VALKYRIAN = "Valkyrian"
    VAMPYRIAN = "Vampyrian"
    WOLVEN = "Wolven"
    # Designations any deck may include regardless of the commander's faction
    UNIVERSAL = "Universal"
    MERCENARY = "Mercenary"
    CELESTIAL = "Celestial"


class Rarity(str, Enum):
    COMMON = "Common"
    UNCOMMON = "Uncommon"
    RARE = "Rare"
    EPIC = "Epic"
    LEGENDARY = "Legendary"
    CELESTIAL = "Celestial"


class CardType(str, Enum):
    """The `type` column of the Studio card table."""

    COMMANDER = "Commander"
    UNIT = "Unit"
    SPELL = "Spell"
    ABILITY = "Ability"
    CORE = "Core"  # Artifact Core
    RESERVE = "Reserve"
    TOKEN = "Token"  # created during play; never deck-legal
    RESOURCE = "Resource"  # the faction resources; derived, never deck-legal


NON_UNIT_TYPES = {CardType.SPELL, CardType.ABILITY, CardType.CORE}


class ReserveType(str, Enum):
    WEAPON = "Weapon"
    ARMOR = "Armor"
    BATTLEFIELD = "Battlefield"
    FEAT = "Feat"


class Evolution(str, Enum):
    BASE = "Base"
    FIRST = "Evol. 1"
    SECOND = "Evol. 2"


# Commander card ids carry their stage: "Satin Ravenheart (Base)"
COMMANDER_STAGE_SUFFIX = re.compile(r"\s*\((Base|Evol\. 1|Evol\. 2)\)$")


class Printing(BaseModel):
    """One printed version of a card, from the Studio `printing` table."""

    card_number: str
    set: str | None = None
    image: str | None = None


class Card(BaseModel):
    id: str  # the card's name; unique per card, stage-suffixed for commanders
    card_type: CardType
    faction: Faction
    rarity: Rarity | None = None
    cost: int | None = None
    attack: int | None = None
    shield_capacity: int | None = None
    shield_power: int | None = None
    health: int | None = None
    faction_subtypes: str | None = None
    # e.g. ["Commander", "Base"], ["Reserve", "Armor", "Potion"]
    attributes: list[str] = []
    rules_text: str = ""
    # A commander's name: the card is only legal in that commander's deck
    specialization: str | None = None
    # Commander-only stats; the Base evolution's drive deck constraints
    resource_count: int | None = None
    mercenary_limit: int | None = None
    core_energy: int | None = None
    hp: int | None = None
    conversion_rate: str | None = None
    printings: list[Printing] = []

    @field_validator(
        "cost",
        "attack",
        "shield_capacity",
        "shield_power",
        "health",
        "resource_count",
        "mercenary_limit",
        "core_energy",
        "hp",
        mode="before",
    )
    @classmethod
    def coerce_numeric_cells(cls, value):
        # Studio number cells hold doubles, untyped ones text; "" means unset.
        # Variable stats print as "*" (set by card effects) — also unset here.
        if value == "" or value is None:
            return None
        try:
            return int(float(value))
        except ValueError:
            return None

    @field_validator(
        "rarity", "faction_subtypes", "specialization", "conversion_rate", mode="before"
    )
    @classmethod
    def blank_text_is_none(cls, value):
        return None if value == "" else value

    @model_validator(mode="after")
    def validate_commander_fields(self):
        if self.card_type == CardType.COMMANDER and self.evolution is None:
            raise ValueError(
                "Commander cards require a stage attribute (Base / Evol. 1 / Evol. 2)"
            )
        return self

    @property
    def name(self) -> str:
        """Display name: the id minus a commander stage suffix."""
        return COMMANDER_STAGE_SUFFIX.sub("", self.id)

    @property
    def evolution(self) -> Evolution | None:
        if self.card_type == CardType.COMMANDER and len(self.attributes) > 1:
            try:
                return Evolution(self.attributes[1])
            except ValueError:
                return None
        return None

    @property
    def conversion_cost(self) -> int | None:
        """Energy rested to generate 1 resource, parsed from the Studio
        cell's "N:1" text (bottom left of the commander card, p. 12)."""
        if self.conversion_rate is None:
            return None
        match = re.match(r"\s*(\d+)", self.conversion_rate)
        return int(match.group(1)) if match else None

    @property
    def reserve_type(self) -> ReserveType | None:
        if self.card_type == CardType.RESERVE and len(self.attributes) > 1:
            try:
                return ReserveType(self.attributes[1])
            except ValueError:
                return None
        return None

    @property
    def is_unit(self) -> bool:
        return self.card_type == CardType.UNIT

    @property
    def is_non_unit(self) -> bool:
        return self.card_type in NON_UNIT_TYPES

    @property
    def is_reserve(self) -> bool:
        return self.card_type == CardType.RESERVE

    @property
    def is_celestial(self) -> bool:
        return self.rarity == Rarity.CELESTIAL or self.faction == Faction.CELESTIAL


class DeckEntry(BaseModel):
    card_id: str
    count: int = Field(ge=1)


class DeckBase(BaseModel):
    """The user-editable parts of a deck, shared by create/update requests.

    There is no resource deck: its contents are fully determined by the
    commander (Resource Count x the faction's resource card), so clients
    derive it for display instead of storing it.
    """

    name: str = Field(min_length=1, max_length=100)
    commander_id: str
    main_deck: list[DeckEntry] = []
    reserve_deck: list[str] = []
    casual: bool = False

    @model_validator(mode="after")
    def validate_no_duplicate_entries(self):
        ids = [e.card_id for e in self.main_deck]
        if len(ids) != len(set(ids)):
            raise ValueError(
                "Duplicate card entries in main_deck; merge counts instead"
            )
        return self


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


class ValidationIssue(BaseModel):
    rule: str
    severity: Severity = Severity.ERROR
    message: str
    cards: list[str] = []

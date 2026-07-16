"""Data-driven deckbuilding rule definitions.

These constants are the single source of truth for the validation engine.
They are exposed via GET /rules so the TypeScript mirror in the frontend
can stay in sync instead of hardcoding its own copies.
"""

MAIN_DECK_SIZE = 50
MAIN_DECK_UNITS = 25
MAIN_DECK_NON_UNITS = 25

# Copies allowed per card name; None means unlimited. Celestial rarity is
# governed by CELESTIAL_DECK_LIMIT (max Celestial cards in the whole deck)
# rather than a per-name copy limit.
RARITY_COPY_LIMITS: dict[str, int | None] = {
    "Common": None,
    "Uncommon": 3,
    "Rare": 3,
    "Epic": 2,
    "Legendary": 1,
    "Celestial": 1,
}

CELESTIAL_DECK_LIMIT = 1

# Reserve deck slots per card type: standard (tournament) and casual variants.
RESERVE_SLOTS = {"Weapon": 2, "Armor": 2, "Battlefield": 2, "Feat": 2}
RESERVE_SLOTS_CASUAL = {"Weapon": 1, "Armor": 1, "Battlefield": 1, "Feat": 2}

# Designations any commander's deck may include regardless of faction.
OPEN_DESIGNATIONS = ["Universal", "Mercenary", "Celestial"]

# Each faction generates its own resource type; the resource deck is
# Resource Count copies of it. (Druidian's Rune is from the card texts —
# the learn-to-play rulebook only tables the other five.)
FACTION_RESOURCES = {
    "Draconian": "Scales",
    "Druidian": "Rune",
    "Necromancer": "Crux",
    "Valkyrian": "Focus",
    "Vampyrian": "Bleed",
    "Wolven": "Rage",
}

# Game setup / turn structure
OPENING_HAND_SIZE = 5  # drawn at setup, then one optional mulligan
TURN_DRAW = 2  # cards drawn in each turn's Draw phase
ENERGY_PLAYS_PER_TURN = 2  # cards placed into the energy field per turn...
FIRST_TURN_ENERGY_PLAYS = 1  # ...but only 1 on the game's very first turn


def rules_manifest() -> dict:
    """JSON-safe bundle of every rule constant, for the frontend mirror."""
    return {
        "mainDeckSize": MAIN_DECK_SIZE,
        "mainDeckUnits": MAIN_DECK_UNITS,
        "mainDeckNonUnits": MAIN_DECK_NON_UNITS,
        "rarityCopyLimits": RARITY_COPY_LIMITS,
        "celestialDeckLimit": CELESTIAL_DECK_LIMIT,
        "reserveSlots": RESERVE_SLOTS,
        "reserveSlotsCasual": RESERVE_SLOTS_CASUAL,
        "openDesignations": OPEN_DESIGNATIONS,
        "factionResources": FACTION_RESOURCES,
        "openingHandSize": OPENING_HAND_SIZE,
        "turnDraw": TURN_DRAW,
        "energyPlaysPerTurn": ENERGY_PLAYS_PER_TURN,
        "firstTurnEnergyPlays": FIRST_TURN_ENERGY_PLAYS,
    }

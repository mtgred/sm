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
    }

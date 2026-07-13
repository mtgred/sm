"""Card data via fireball's Studio dynamic table system.

Cards are managed as Studio tables (fireball/server/src/tables.ts) in the
ring's database: `card` holds one row per card keyed by name (`id`), and
`printing` holds printed versions (card number, set, image) joined to cards
by its `name` column. Studio cells are loosely typed — number columns store
doubles, untyped columns store text — so rows are mapped into the typed Card
model here (with coercion handled by the model's validators).
"""

import logging
import os
from pydantic import ValidationError
from .db import db
from .models import Card, Printing

logger = logging.getLogger(__name__)

CARDS_TABLE = os.environ.get("CARDS_TABLE", "card")
PRINTINGS_TABLE = os.environ.get("PRINTINGS_TABLE", "printing")

# Studio colId -> Card field
COLUMN_FIELDS = {
    "id": "id",
    "type": "card_type",
    "faction": "faction",
    "rarity": "rarity",
    "cost": "cost",
    "attack": "attack",
    "shield-capacity": "shield_capacity",
    "shield-power": "shield_power",
    "health": "health",
    "faction-subtypes": "faction_subtypes",
    "attributes": "attributes",
    "text": "rules_text",
    "specialization": "specialization",
    "resource-count": "resource_count",
    "mercenary-limit": "mercenary_limit",
    "core-energy": "core_energy",
    "hp": "hp",
    "conversion-rate": "conversion_rate",
}

# Attributes render on cards as e.g. "Reserve - Armor - Potion"
ATTRIBUTES_SEPARATOR = " - "

def image_url(filename: str) -> str:
    # Table images are uploaded against the printing table and served
    # statically by the fireball server
    return f"/soulmasters/asset/{PRINTINGS_TABLE}/{filename}"


def row_to_card(row: dict, printings: list[Printing] | None = None) -> Card:
    data: dict = {"printings": printings or []}
    for col_id, field in COLUMN_FIELDS.items():
        value = row.get(col_id)
        if value is None:
            continue
        if field == "attributes" and isinstance(value, str):
            value = [p.strip() for p in value.split(ATTRIBUTES_SEPARATOR) if p.strip()]
        elif field == "rules_text" and isinstance(value, str):
            value = value.replace("\r\n", "\n")
        data[field] = value
    return Card(**data)


def load_printings() -> dict[str, list[Printing]]:
    """Printings grouped by the card name they belong to."""
    by_card: dict[str, list[Printing]] = {}
    for row in db[PRINTINGS_TABLE].find({}, {"_id": 0}).sort("id", 1):
        if not row.get("id") or not row.get("name"):
            continue
        printing = Printing(
            card_number=row["id"],
            set=row.get("set") or None,
            image=image_url(row["image"]) if row.get("image") else None,
        )
        by_card.setdefault(row["name"], []).append(printing)
    return by_card


def load_cards() -> dict[str, Card]:
    """The full card pool from the Studio tables. Rows that don't form a
    valid card yet (e.g. half-filled rows being edited in Studio) are skipped
    so a work-in-progress row can't take the deckbuilder down."""
    printings = load_printings()
    pool: dict[str, Card] = {}
    for row in db[CARDS_TABLE].find({}, {"_id": 0}):
        if not row.get("id"):
            continue
        try:
            card = row_to_card(row, printings.get(row["id"]))
        except (ValidationError, ValueError) as err:
            logger.warning("Skipping invalid card row %r: %s", row.get("id"), err)
            continue
        pool[card.id] = card
    return pool

import pytest
from pydantic import ValidationError

from ..models import CardType, Evolution, Faction, Printing, Rarity, ReserveType
from ..studio import row_to_card


def test_row_to_card_maps_a_unit_row():
    # Shaped like a real row from the Studio `card` table
    card = row_to_card(
        {
            "type": "Unit",
            "cost": 1,
            "attack": 1,
            "shield-capacity": 0,
            "health": 2,
            "shield-power": 1,
            "rarity": "Rare",
            "resource-count": "",
            "core-energy": "",
            "hp": "",
            "mercenary-limit": "",
            "conversion-rate": "",
            "faction": "Valkyrian",
            "faction-subtypes": "5th Army",
            "specialization": "",
            "attributes": "Unit",
            "text": "Scout (Can attack ready Stealth units.)\r\nEnduring.",
            "id": "Malagant Zal",
        }
    )
    assert card.name == "Malagant Zal"
    assert card.card_type == CardType.UNIT
    assert card.faction == Faction.VALKYRIAN
    assert card.rarity == Rarity.RARE
    assert card.shield_capacity == 0
    assert card.resource_count is None
    assert card.specialization is None
    assert card.faction_subtypes == "5th Army"
    assert "\r" not in card.rules_text


def test_row_to_card_maps_a_commander_row():
    card = row_to_card(
        {
            "id": "Satin Ravenheart (Base)",
            "type": "Commander",
            "faction": "Vampyrian",
            "rarity": "Legendary",
            "attack": 3,
            "shield-capacity": 1,
            "attributes": "Commander - Base",
            "resource-count": "10",
            "core-energy": "4",
            "hp": "10",
            "mercenary-limit": "3",
            "conversion-rate": "4:1",
        }
    )
    assert card.name == "Satin Ravenheart"
    assert card.evolution == Evolution.BASE
    assert card.resource_count == 10
    assert card.core_energy == 4
    assert card.mercenary_limit == 3
    assert card.hp == 10
    assert card.conversion_rate == "4:1"


def test_row_to_card_parses_reserve_and_evolution_attributes():
    armor = row_to_card(
        {
            "id": "Shadow Armor",
            "type": "Reserve",
            "faction": "Wolven",
            "attributes": "Reserve - Armor - Potion",
        }
    )
    assert armor.reserve_type == ReserveType.ARMOR
    assert armor.attributes == ["Reserve", "Armor", "Potion"]

    evol = row_to_card(
        {
            "id": "Satin Ravenheart (Evol. 2)",
            "type": "Commander",
            "faction": "Vampyrian",
            "attributes": "Commander - Evol. 2",
        }
    )
    assert evol.evolution == Evolution.SECOND
    assert evol.name == "Satin Ravenheart"


def test_row_to_card_attaches_printings():
    card = row_to_card(
        {"id": "Malagant Zal", "type": "Unit", "faction": "Valkyrian"},
        [Printing(card_number="SM-AW-001", set="Awakenings", image="/x/SM-AW-001.jpg")],
    )
    assert card.printings[0].card_number == "SM-AW-001"


def test_row_to_card_accepts_variable_stats():
    # e.g. Blood Dragon prints health as "*" (set by a card effect)
    card = row_to_card(
        {"id": "Blood Dragon", "type": "Unit", "faction": "Vampyrian", "health": "*"}
    )
    assert card.health is None


def test_row_to_card_rejects_invalid_rows():
    with pytest.raises(ValidationError):
        row_to_card({"id": "Bad", "type": "Nope", "faction": "Wolven"})
    with pytest.raises(ValidationError):
        # A commander without a stage attribute is not a usable card
        row_to_card({"id": "Bad", "type": "Commander", "faction": "Wolven"})

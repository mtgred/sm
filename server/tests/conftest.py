import pytest

from ..models import Card, DeckBase, DeckEntry


def card(id: str, card_type: str = "Unit", faction: str = "Wolven", **kwargs) -> Card:
    return Card(id=id, card_type=card_type, faction=faction, **kwargs)


def reserve_card(id: str, slot: str, **kwargs) -> Card:
    return card(id, card_type="Reserve", attributes=["Reserve", slot], **kwargs)


@pytest.fixture
def pool() -> dict[str, Card]:
    cards = [
        card(
            "Keshi Savageclaw (Base)",
            card_type="Commander",
            rarity="Legendary",
            attributes=["Commander", "Base"],
            resource_count=4,
            mercenary_limit=2,
            core_energy=6,
            hp=10,
            conversion_rate="3:1",
        ),
        # Evol. 1's cells are unset in Studio: stage lookups fall back to Base
        card(
            "Keshi Savageclaw (Evol. 1)",
            card_type="Commander",
            attributes=["Commander", "Evol. 1"],
        ),
        card(
            "Athena Stormkal (Base)",
            card_type="Commander",
            faction="Valkyrian",
            rarity="Legendary",
            attributes=["Commander", "Base"],
            resource_count=5,
            mercenary_limit=1,
            core_energy=4,
            hp=10,
        ),
        # Units (costs cover the casting tests: 2, free, and unset-in-Studio)
        card("Common Unit", rarity="Common", cost=2, attack=2, health=2),
        card("Uncommon Unit", rarity="Uncommon", cost=0),
        card("Rare Unit", rarity="Rare"),
        card("Epic Unit", rarity="Epic"),
        card("Legendary Unit", rarity="Legendary"),
        card("Merc Unit", faction="Mercenary", rarity="Common"),
        card("Universal Unit", faction="Universal", rarity="Common"),
        card("Celestial Unit", faction="Celestial", rarity="Celestial"),
        card("Offfaction Unit", faction="Necromancer", rarity="Common"),
        card("Battle Token", card_type="Token"),
        card("Rage", card_type="Resource"),
        # Non-units
        card("Common Spell", card_type="Spell", rarity="Common", cost=1),
        card("Merc Spell", card_type="Spell", faction="Mercenary", rarity="Common"),
        card("Celestial Spell", card_type="Spell", rarity="Celestial"),
        card(
            "Keshi Ability",
            card_type="Ability",
            rarity="Common",
            specialization="Keshi Savageclaw",
        ),
        card(
            "Athena Ability",
            card_type="Ability",
            rarity="Common",
            specialization="Athena Stormkal",
        ),
        card("Energy Core", card_type="Core", faction="Universal", rarity="Common"),
        # Reserve (Armor Two's cost is unset-in-Studio for the casting tests)
        reserve_card("Weapon One", "Weapon", cost=1),
        reserve_card("Weapon Two", "Weapon", cost=2),
        reserve_card("Weapon Three", "Weapon", cost=1),
        reserve_card("Armor One", "Armor", cost=1),
        reserve_card("Armor Two", "Armor"),
        reserve_card("Battlefield One", "Battlefield", cost=1),
        reserve_card("Battlefield Two", "Battlefield", cost=2),
        reserve_card("Feat One", "Feat", cost=0),
        reserve_card("Feat Two", "Feat", cost=1),
    ]
    return {c.id: c for c in cards}


def legal_deck(**overrides) -> DeckBase:
    """25 common units / 25 non-units (6 cores for Core Energy 6), standard
    2/2/2/2 reserve — legal for the Keshi Savageclaw (Base) fixture."""
    defaults = dict(
        name="Test deck",
        commander_id="Keshi Savageclaw (Base)",
        main_deck=[
            DeckEntry(card_id="Common Unit", count=25),
            DeckEntry(card_id="Common Spell", count=19),
            DeckEntry(card_id="Energy Core", count=6),
        ],
        reserve_deck=[
            "Weapon One",
            "Weapon Two",
            "Armor One",
            "Armor Two",
            "Battlefield One",
            "Battlefield Two",
            "Feat One",
            "Feat Two",
        ],
    )
    return DeckBase(**{**defaults, **overrides})

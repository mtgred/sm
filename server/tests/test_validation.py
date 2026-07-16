from ..models import DeckEntry
from ..validation import validate_deck
from .conftest import legal_deck


def rules_of(issues):
    return {i.rule for i in issues}


def swap_entry(deck, card_id, new_id=None, count=None):
    """Replace/adjust one main deck entry, keeping the others."""
    entries = []
    for entry in deck.main_deck:
        if entry.card_id == card_id:
            entries.append(
                DeckEntry(
                    card_id=new_id or entry.card_id,
                    count=count if count is not None else entry.count,
                )
            )
        else:
            entries.append(entry)
    deck.main_deck = entries
    return deck


def test_legal_deck_has_no_issues(pool):
    assert validate_deck(legal_deck(), pool) == []


def test_unknown_cards_reported(pool):
    deck = legal_deck()
    deck.reserve_deck = deck.reserve_deck[:-1] + ["Nope"]
    issues = validate_deck(deck, pool)
    assert any(i.rule == "unknown-card" and i.cards == ["Nope"] for i in issues)


def test_commander_must_be_commander_card(pool):
    issues = validate_deck(legal_deck(commander_id="Common Unit"), pool)
    assert rules_of(issues) == {"commander-invalid"}


def test_commander_must_be_base_stage(pool):
    issues = validate_deck(legal_deck(commander_id="Keshi Savageclaw (Evol. 1)"), pool)
    assert rules_of(issues) == {"commander-invalid"}


def test_main_deck_size_and_split(pool):
    deck = legal_deck()
    swap_entry(deck, "Common Spell", count=18)  # 49 cards, 24 non-units
    issues = validate_deck(deck, pool)
    assert {"main-deck-size", "non-unit-count"} <= rules_of(issues)
    assert "unit-count" not in rules_of(issues)


def test_wrong_split_at_correct_total(pool):
    deck = legal_deck()
    swap_entry(deck, "Common Unit", count=24)
    swap_entry(deck, "Common Spell", count=20)  # 50 total but 24/26
    issues = validate_deck(deck, pool)
    assert {"unit-count", "non-unit-count"} <= rules_of(issues)
    assert "main-deck-size" not in rules_of(issues)


def test_main_deck_rejects_reserve_token_and_resource_cards(pool):
    deck = legal_deck()
    deck.main_deck += [
        DeckEntry(card_id="Weapon Three", count=1),
        DeckEntry(card_id="Battle Token", count=1),
        DeckEntry(card_id="Rage", count=1),
    ]
    issues = validate_deck(deck, pool)
    assert any(
        i.rule == "main-deck-card-types"
        and set(i.cards) == {"Weapon Three", "Battle Token", "Rage"}
        for i in issues
    )


def test_copy_limits_by_rarity(pool):
    for card_id, limit in [
        ("Uncommon Unit", 3),
        ("Rare Unit", 3),
        ("Epic Unit", 2),
        ("Legendary Unit", 1),
    ]:
        deck = legal_deck()
        swap_entry(deck, "Common Unit", count=25 - limit - 1)
        deck.main_deck.append(DeckEntry(card_id=card_id, count=limit + 1))
        issues = validate_deck(deck, pool)
        assert "copy-limit" in rules_of(issues), card_id

        deck = legal_deck()
        swap_entry(deck, "Common Unit", count=25 - limit)
        deck.main_deck.append(DeckEntry(card_id=card_id, count=limit))
        assert "copy-limit" not in rules_of(validate_deck(deck, pool)), card_id


def test_commons_are_unlimited(pool):
    assert "copy-limit" not in rules_of(validate_deck(legal_deck(), pool))


def test_celestial_limit_across_units_and_spells(pool):
    deck = legal_deck()
    swap_entry(deck, "Common Unit", count=24)
    deck.main_deck.append(DeckEntry(card_id="Celestial Unit", count=1))
    swap_entry(deck, "Common Spell", count=18)
    deck.main_deck.append(DeckEntry(card_id="Celestial Spell", count=1))
    issues = validate_deck(deck, pool)
    assert "celestial-limit" in rules_of(issues)
    # copy-limit must not double-report: these are single copies of two
    # different names, only the whole-deck Celestial cap is violated
    assert "copy-limit" not in rules_of(issues)


def test_single_celestial_is_legal(pool):
    deck = legal_deck()
    swap_entry(deck, "Common Unit", count=24)
    deck.main_deck.append(DeckEntry(card_id="Celestial Unit", count=1))
    assert validate_deck(deck, pool) == []


def test_two_copies_of_same_celestial_hit_both_rules(pool):
    deck = legal_deck()
    swap_entry(deck, "Common Unit", count=23)
    deck.main_deck.append(DeckEntry(card_id="Celestial Unit", count=2))
    issues = validate_deck(deck, pool)
    assert {"celestial-limit", "copy-limit"} <= rules_of(issues)


def test_faction_lock(pool):
    deck = legal_deck()
    swap_entry(deck, "Common Unit", count=24)
    deck.main_deck.append(DeckEntry(card_id="Offfaction Unit", count=1))
    issues = validate_deck(deck, pool)
    assert any(
        i.rule == "faction-legality" and i.cards == ["Offfaction Unit"] for i in issues
    )


def test_universal_mercenary_celestial_bypass_faction_lock(pool):
    deck = legal_deck()
    swap_entry(deck, "Common Unit", count=22)
    deck.main_deck += [
        DeckEntry(card_id="Universal Unit", count=1),
        DeckEntry(card_id="Merc Unit", count=1),
        DeckEntry(card_id="Celestial Unit", count=1),
    ]
    assert "faction-legality" not in rules_of(validate_deck(deck, pool))


def test_mercenary_limit_split_across_units_and_non_units(pool):
    # Commander allows 2 mercenaries; 2 merc units + 1 merc spell = 3
    deck = legal_deck()
    swap_entry(deck, "Common Unit", count=23)
    deck.main_deck.append(DeckEntry(card_id="Merc Unit", count=2))
    swap_entry(deck, "Common Spell", count=18)
    deck.main_deck.append(DeckEntry(card_id="Merc Spell", count=1))
    issues = validate_deck(deck, pool)
    assert any(
        i.rule == "mercenary-limit" and set(i.cards) == {"Merc Unit", "Merc Spell"}
        for i in issues
    )


def test_mercenaries_at_limit_are_legal(pool):
    deck = legal_deck()
    swap_entry(deck, "Common Unit", count=24)
    deck.main_deck.append(DeckEntry(card_id="Merc Unit", count=1))
    swap_entry(deck, "Common Spell", count=18)
    deck.main_deck.append(DeckEntry(card_id="Merc Spell", count=1))
    assert "mercenary-limit" not in rules_of(validate_deck(deck, pool))


def test_artifact_core_count_must_match_core_energy(pool):
    deck = legal_deck()
    swap_entry(deck, "Energy Core", count=5)
    swap_entry(deck, "Common Spell", count=20)
    issues = validate_deck(deck, pool)
    assert "core-count" in rules_of(issues)
    assert "main-deck-size" not in rules_of(issues)


def test_reserve_slot_counts(pool):
    deck = legal_deck()
    deck.reserve_deck = [
        "Weapon One",
        "Weapon Two",
        "Weapon Three",
        "Armor One",
        "Battlefield One",
        "Battlefield Two",
        "Feat One",
        "Feat Two",
    ]
    issues = [i for i in validate_deck(deck, pool) if i.rule == "reserve-slots"]
    assert len(issues) == 2  # 3 weapons, 1 armor


def test_reserve_uniqueness(pool):
    deck = legal_deck()
    deck.reserve_deck = [
        "Weapon One",
        "Weapon One",
        "Armor One",
        "Armor Two",
        "Battlefield One",
        "Battlefield Two",
        "Feat One",
        "Feat Two",
    ]
    issues = validate_deck(deck, pool)
    assert "reserve-unique" in rules_of(issues)


def test_reserve_rejects_main_deck_cards(pool):
    deck = legal_deck()
    deck.reserve_deck = deck.reserve_deck[:-1] + ["Common Unit"]
    issues = validate_deck(deck, pool)
    assert "reserve-card-types" in rules_of(issues)


def test_casual_reserve_mode(pool):
    casual_reserve = [
        "Weapon One",
        "Armor One",
        "Battlefield One",
        "Feat One",
        "Feat Two",
    ]
    assert (
        validate_deck(legal_deck(reserve_deck=casual_reserve, casual=True), pool) == []
    )
    issues = validate_deck(legal_deck(reserve_deck=casual_reserve), pool)
    assert "reserve-slots" in rules_of(issues)


def test_specialization_matching_commander_is_legal(pool):
    deck = legal_deck()
    swap_entry(deck, "Common Spell", count=18)
    deck.main_deck.append(DeckEntry(card_id="Keshi Ability", count=1))
    assert validate_deck(deck, pool) == []


def test_specialization_mismatch(pool):
    deck = legal_deck()
    swap_entry(deck, "Common Spell", count=18)
    deck.main_deck.append(DeckEntry(card_id="Athena Ability", count=1))
    issues = validate_deck(deck, pool)
    assert any(
        i.rule == "specialization" and i.cards == ["Athena Ability"] for i in issues
    )


def test_issue_shape(pool):
    deck = legal_deck(commander_id="Athena Stormkal (Base)")  # wrong faction
    for i in validate_deck(deck, pool):
        assert i.rule and i.message and i.severity == "error"

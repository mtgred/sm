"""Authoritative deck validation engine.

Pure functions over Pydantic models: given a deck and the card pool it
references, return a list of structured issues. An empty list means the
deck is tournament legal (or casual legal when deck.casual is set).

The resource deck is not validated because it is not stored: it is fully
determined by the commander (Resource Count x faction resource type).
"""

from collections import Counter

from .models import (
    Card,
    CardType,
    DeckBase,
    Evolution,
    Faction,
    Rarity,
    Severity,
    ValidationIssue,
)
from .rules import (
    CELESTIAL_DECK_LIMIT,
    MAIN_DECK_NON_UNITS,
    MAIN_DECK_SIZE,
    MAIN_DECK_UNITS,
    RARITY_COPY_LIMITS,
    RESERVE_SLOTS,
    RESERVE_SLOTS_CASUAL,
)


def issue(
    rule: str,
    message: str,
    cards: list[str] | None = None,
    severity: Severity = Severity.ERROR,
) -> ValidationIssue:
    return ValidationIssue(
        rule=rule, severity=severity, message=message, cards=cards or []
    )


def validate_deck(deck: DeckBase, pool: dict[str, Card]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    referenced = [
        deck.commander_id,
        *(e.card_id for e in deck.main_deck),
        *deck.reserve_deck,
    ]
    unknown = sorted({cid for cid in referenced if cid not in pool})
    if unknown:
        issues.append(issue("unknown-card", "Deck references unknown cards", unknown))

    commander = pool.get(deck.commander_id)
    if not commander or commander.card_type != CardType.COMMANDER:
        issues.append(
            issue(
                "commander-invalid",
                "Deck must be led by a commander card",
                [deck.commander_id],
            )
        )
        return issues
    if commander.evolution != Evolution.BASE or commander.resource_count is None:
        issues.append(
            issue(
                "commander-invalid",
                "Commander must be the Base stage (its stats drive deck constraints)",
                [commander.id],
            )
        )
        return issues

    main = [(pool[e.card_id], e.count) for e in deck.main_deck if e.card_id in pool]
    reserve = [pool[cid] for cid in deck.reserve_deck if cid in pool]

    issues += check_main_deck_composition(main)
    issues += check_copy_limits(main)
    issues += check_celestial_limit(main, reserve)
    issues += check_faction_legality(commander, main)
    issues += check_mercenary_limit(commander, main)
    issues += check_core_energy(commander, main)
    issues += check_reserve_deck(reserve, casual=deck.casual)
    issues += check_specializations(commander, main, reserve)
    return issues


def check_main_deck_composition(main: list[tuple[Card, int]]) -> list[ValidationIssue]:
    issues = []
    wrong_type = [card.id for card, _ in main if not (card.is_unit or card.is_non_unit)]
    if wrong_type:
        issues.append(
            issue(
                "main-deck-card-types",
                "Main deck may only contain Unit, Spell, Ability and Artifact Core cards",
                wrong_type,
            )
        )
    units = sum(count for card, count in main if card.is_unit)
    non_units = sum(count for card, count in main if card.is_non_unit)
    total = units + non_units
    if total != MAIN_DECK_SIZE:
        issues.append(
            issue(
                "main-deck-size",
                f"Main deck must be exactly {MAIN_DECK_SIZE} cards (currently {total})",
            )
        )
    if units != MAIN_DECK_UNITS:
        issues.append(
            issue(
                "unit-count",
                f"Main deck must contain exactly {MAIN_DECK_UNITS} unit cards (currently {units})",
            )
        )
    if non_units != MAIN_DECK_NON_UNITS:
        issues.append(
            issue(
                "non-unit-count",
                f"Main deck must contain exactly {MAIN_DECK_NON_UNITS} non-unit cards (currently {non_units})",
            )
        )
    return issues


def check_copy_limits(main: list[tuple[Card, int]]) -> list[ValidationIssue]:
    # Cards with the same name are the same card, whatever their printing.
    counts: Counter[str] = Counter()
    ids_by_name: dict[str, list[str]] = {}
    rarity_by_name: dict[str, Rarity | None] = {}
    for card, count in main:
        counts[card.name] += count
        ids_by_name.setdefault(card.name, []).append(card.id)
        rarity_by_name.setdefault(card.name, card.rarity)

    issues = []
    for name, total in counts.items():
        rarity = rarity_by_name[name]
        limit = RARITY_COPY_LIMITS.get(rarity.value) if rarity else None
        if limit is not None and total > limit:
            issues.append(
                issue(
                    "copy-limit",
                    f"{name} is {rarity.value}: maximum {limit} copies per deck (currently {total})",
                    ids_by_name[name],
                )
            )
    return issues


def check_celestial_limit(
    main: list[tuple[Card, int]], reserve: list[Card]
) -> list[ValidationIssue]:
    celestial_ids = [
        card.id for card, count in main for _ in range(count) if card.is_celestial
    ]
    celestial_ids += [card.id for card in reserve if card.is_celestial]
    if len(celestial_ids) > CELESTIAL_DECK_LIMIT:
        return [
            issue(
                "celestial-limit",
                f"Maximum {CELESTIAL_DECK_LIMIT} Celestial card in your whole deck "
                f"(currently {len(celestial_ids)})",
                sorted(set(celestial_ids)),
            )
        ]
    return []


def is_faction_legal(commander: Card, card: Card) -> bool:
    return (
        card.faction == commander.faction
        or card.faction in (Faction.UNIVERSAL, Faction.MERCENARY, Faction.CELESTIAL)
        or card.rarity == Rarity.CELESTIAL
    )


def check_faction_legality(
    commander: Card, main: list[tuple[Card, int]]
) -> list[ValidationIssue]:
    offending = [card.id for card, _ in main if not is_faction_legal(commander, card)]
    if offending:
        return [
            issue(
                "faction-legality",
                f"Only {commander.faction.value}, Universal, Mercenary and Celestial cards "
                f"are legal with {commander.name}",
                offending,
            )
        ]
    return []


def check_mercenary_limit(
    commander: Card, main: list[tuple[Card, int]]
) -> list[ValidationIssue]:
    mercs = [(card, count) for card, count in main if card.faction == Faction.MERCENARY]
    total = sum(count for _, count in mercs)
    limit = commander.mercenary_limit or 0
    if total > limit:
        return [
            issue(
                "mercenary-limit",
                f"{commander.name} allows at most {limit} Mercenary cards (currently {total})",
                [card.id for card, _ in mercs],
            )
        ]
    return []


def check_core_energy(
    commander: Card, main: list[tuple[Card, int]]
) -> list[ValidationIssue]:
    cores = sum(count for card, count in main if card.card_type == CardType.CORE)
    target = commander.core_energy or 0
    if cores != target:
        return [
            issue(
                "core-count",
                f"Main deck must include exactly {target} Artifact Core cards "
                f"to match {commander.name}'s Core Energy (currently {cores})",
            )
        ]
    return []


def check_reserve_deck(reserve: list[Card], casual: bool) -> list[ValidationIssue]:
    slots = RESERVE_SLOTS_CASUAL if casual else RESERVE_SLOTS
    label = "casual" if casual else "standard"
    issues = []

    wrong_type = [card.id for card in reserve if card.reserve_type is None]
    if wrong_type:
        issues.append(
            issue(
                "reserve-card-types",
                "Reserve deck may only contain Weapon, Armor, Battlefield and Feat cards",
                wrong_type,
            )
        )

    name_counts = Counter(card.name for card in reserve)
    dupes = [card.id for card in reserve if name_counts[card.name] > 1]
    if dupes:
        issues.append(
            issue(
                "reserve-unique", "Each Reserve card must be unique", sorted(set(dupes))
            )
        )

    for slot_type, wanted in slots.items():
        have = sum(
            1
            for card in reserve
            if card.reserve_type and card.reserve_type.value == slot_type
        )
        if have != wanted:
            issues.append(
                issue(
                    "reserve-slots",
                    f"Reserve deck ({label}) needs exactly {wanted} {slot_type} "
                    f"card{'s' if wanted != 1 else ''} (currently {have})",
                )
            )
    return issues


def check_specializations(
    commander: Card, main: list[tuple[Card, int]], reserve: list[Card]
) -> list[ValidationIssue]:
    cards = [card for card, _ in main] + reserve
    offending = [
        card.id
        for card in cards
        if card.specialization and card.specialization != commander.name
    ]
    if offending:
        return [
            issue(
                "specialization",
                f"These cards are specialized to a different commander than {commander.name}",
                offending,
            )
        ]
    return []

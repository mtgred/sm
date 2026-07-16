"""Initial game state construction, modeled on uprising/server/game_setup.py.

`create_game` turns the lobby's seated players (each with their deck document
snapshotted at start time) plus the current card pool into the `state` stored
on the game document. Setup follows the rulebook's "Playing a Game" steps:
shuffled main deck, resource deck derived from the commander (Resource Count
copies of the faction's resource), commander with its evolution stages,
face-down reserve, a random first player, and 5-card opening hands.

The game then opens in the `mulligan` phase — each player may once put any
number of hand cards on the bottom of their deck and redraw that many (the
deck is shuffled afterwards, per the rulebook). Once both players have
resolved it, the first player's turn begins: upkeep (nothing to ready yet)
and the 2-card draw phase. Turn logic beyond that will grow in its own
module, like uprising's game.py.
"""

from random import randrange, sample, shuffle
from uuid import uuid4

from .models import Card, CardType, Evolution
from .rules import FACTION_RESOURCES, OPENING_HAND_SIZE, TURN_DRAW

GAME_SIZE = 2  # Soulmasters is a two-player duel

STAGE_ORDER = [Evolution.BASE, Evolution.FIRST, Evolution.SECOND]


def create_deck(entries) -> list[dict]:
    """Physical cards from (card_id, count) pairs: a uid per copy, shuffled.
    Index 0 is the top of the deck."""
    deck = [
        {"id": card_id, "uid": str(uuid4())}
        for card_id, count in entries
        for _ in range(count)
    ]
    return sample(deck, len(deck))


def log(state: dict, msg: str, player: dict | None = None):
    entry: dict = {"msg": msg}
    if player:
        entry["user"] = player["user"]
    state["log"].append(entry)


def draw(player: dict, count: int) -> int:
    """Move up to `count` cards from the top of the deck to the hand.
    Running out of cards only matters once turn logic handles losing."""
    drawn = player["deck"][:count]
    player["deck"] = player["deck"][count:]
    player["hand"] += drawn
    return len(drawn)


def commander_stages(base: Card, pool: dict[str, Card]) -> list[str]:
    """The commander's card ids in evolution order; missing stages (still
    unreleased or unparsed in Studio) are simply absent."""
    return [
        f"{base.name} ({stage.value})"
        for stage in STAGE_ORDER
        if f"{base.name} ({stage.value})" in pool
    ]


def create_player(user: dict, deck: dict, pool: dict[str, Card]) -> dict:
    base = pool.get(deck["commander_id"])
    if not base or base.card_type != CardType.COMMANDER or base.evolution != Evolution.BASE:
        raise ValueError(
            f"{deck['name']} is not led by a Base-stage commander in the card pool"
        )
    if base.hp is None:
        raise ValueError(f"{base.id} has no HP in the card pool")

    player = {
        "user": {"username": user["username"], "hash": user["hash"]},
        # `stage` indexes into `stages`; evolving advances it and re-reads HP
        "commander": {"stages": commander_stages(base, pool), "stage": 0},
        "hp": base.hp,
        "maxHp": base.hp,
        # The resource deck is Resource Count copies of one identical card,
        # so two counters model it: deck -> field on generate, back on spend.
        "resource": FACTION_RESOURCES.get(base.faction.value, "Resource"),
        "resourceDeck": base.resource_count or 0,
        "resourceField": 0,
        "deck": create_deck((e["card_id"], e["count"]) for e in deck["main_deck"]),
        "hand": [],
        "discard": [],
        "battleground": [],
        "equipment": [],  # at most one active Weapon and one active Armor
        "battlefield": None,
        # Cards in the energy field carry faceUp/resting; energyPlays counts
        # this turn's placements (upkeep resets it once turns pass).
        "energyField": [],
        "energyPlays": 0,
        "reserve": [{"id": cid, "uid": str(uuid4())} for cid in deck["reserve_deck"]],
        "mulliganed": False,
        "prompts": [],
    }
    draw(player, OPENING_HAND_SIZE)
    return player


def create_game(seats: list[dict], pool: dict[str, Card]) -> dict:
    """Initial state from lobby seats: [{"user": {...}, "deck": deck_doc}]."""
    if len(seats) != GAME_SIZE:
        raise ValueError(f"Game requires {GAME_SIZE} players")

    seats = sample(seats, len(seats))
    state = {
        "round": 1,
        "phase": "mulligan",
        "firstPlayer": randrange(GAME_SIZE),
        "activePlayer": None,  # set when the mulligan phase resolves
        "log": [],
        "players": [create_player(s["user"], s["deck"], pool) for s in seats],
    }
    for player in state["players"]:
        log(state, f"draws {len(player['hand'])} cards", player)
    first = state["players"][state["firstPlayer"]]
    log(state, f"{first['user']['username']} will take the first turn")
    return state


def mulligan(state: dict, player: dict, data, pool=None) -> dict:
    """Resolve the player's one mulligan decision: `data` is the list of hand
    uids to put on the bottom of the deck (empty keeps the hand). `pool` is
    unused; it's part of the uniform game-action signature (see game.py)."""
    if state.get("phase") != "mulligan":
        return {"error": "The mulligan phase is over"}
    if player["mulliganed"]:
        return {"error": "You have already resolved your mulligan"}
    uids = data or []
    hand_uids = [c["uid"] for c in player["hand"]]
    if not isinstance(uids, list) or len(set(uids)) != len(uids) or not set(uids) <= set(hand_uids):
        return {"error": "Those cards are not in your hand"}

    if uids:
        returned = [c for c in player["hand"] if c["uid"] in uids]
        player["hand"] = [c for c in player["hand"] if c["uid"] not in uids]
        player["deck"] += returned  # bottom of the deck
        draw(player, len(returned))
        shuffle(player["deck"])  # "If you do, shuffle" — after redrawing
        log(state, f"puts {len(returned)} cards back and redraws", player)
    else:
        log(state, "keeps their hand", player)

    player["mulliganed"] = True
    if all(p["mulliganed"] for p in state["players"]):
        begin_first_turn(state)
    return state


def begin_first_turn(state: dict):
    """Both mulligans resolved: the first player takes their upkeep (nothing
    is resting yet) and draw phase, and play begins."""
    state["phase"] = "main"
    state["activePlayer"] = state["firstPlayer"]
    player = state["players"][state["firstPlayer"]]
    drawn = draw(player, TURN_DRAW)
    log(state, "Round 1 begins")
    log(state, f"draws {drawn} cards", player)

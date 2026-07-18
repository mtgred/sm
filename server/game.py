"""In-game turn actions, growing alongside game_setup.py the way uprising's
game.py does. Every action shares the (state, player, data, pool) signature
used by main.GAME_ACTIONS: mutate the state dict in place and return it, or
return {"error": ...} without touching anything.
"""

from .game_setup import draw, log
from .models import Card, CardType, ReserveType
from .rules import (
    BATTLEGROUND_CAPACITY,
    ENERGY_PLAYS_PER_TURN,
    FIRST_TURN_ENERGY_PLAYS,
    RESERVE_CASTS_PER_ROUND,
    RESERVE_UNLOCK_ROUND,
    TURN_DRAW,
)


def energy_limit(player: dict, pool: dict[str, Card]) -> int:
    """The commander's Core Energy — the energy field's size cap. Read from
    the current evolution stage, falling back through earlier stages when a
    stage's cell is still unset in Studio."""
    stages = player["commander"]["stages"][: player["commander"]["stage"] + 1]
    for stage_id in reversed(stages):
        card = pool.get(stage_id)
        if card and card.core_energy is not None:
            return card.core_energy
    return 0


def play_energy(state: dict, player: dict, data, pool: dict[str, Card]) -> dict:
    """Place a hand card into the energy field (rulebook pp. 15-16): any card
    face down, Artifact Cores optionally face up (only face-up skills are
    active). Playing a core face up may swap another energy card back to hand
    — the one way to add energy once the field is at the commander's Core
    Energy — and the core enters play resting if the swapped card was, so a
    swap never gains ready energy. `data` is {"uid", "faceUp"?, "swap"?}."""
    if state.get("phase") != "main":
        return {"error": "Energy can only be played in your main phase"}
    if state["players"][state["activePlayer"]] is not player:
        return {"error": "It is not your turn"}
    data = data if isinstance(data, dict) else {}
    uid, swap_uid, face_up = data.get("uid"), data.get("swap"), bool(data.get("faceUp"))

    played = next((c for c in player["hand"] if c["uid"] == uid), None)
    if not played:
        return {"error": "That card is not in your hand"}
    card = pool.get(played["id"])
    if face_up and (not card or card.card_type != CardType.CORE):
        return {"error": "Only Artifact Cores can be played face up"}
    if swap_uid and not face_up:
        return {"error": "Swapping requires playing an Artifact Core face up"}

    first_turn = state["round"] == 1 and state["activePlayer"] == state["firstPlayer"]
    allowed = FIRST_TURN_ENERGY_PLAYS if first_turn else ENERGY_PLAYS_PER_TURN
    # .get: games started before the counter existed have no energyPlays key
    if player.get("energyPlays", 0) >= allowed:
        return {"error": f"You have already played {allowed} energy this turn"}

    swapped = None
    if swap_uid:
        swapped = next((c for c in player["energyField"] if c["uid"] == swap_uid), None)
        if not swapped:
            return {"error": "That card is not in your energy field"}
    elif len(player["energyField"]) >= (limit := energy_limit(player, pool)):
        return {"error": f"Your energy field is full (Core Energy {limit})"}

    player["hand"] = [c for c in player["hand"] if c["uid"] != uid]
    entry = {
        "id": played["id"],
        "uid": played["uid"],
        "faceUp": face_up,
        # the swapped-in core inherits the outgoing card's rest
        "resting": bool(swapped and swapped.get("resting")),
    }
    if swapped:
        player["energyField"] = [c for c in player["energyField"] if c["uid"] != swap_uid]
        player["hand"].append({"id": swapped["id"], "uid": swapped["uid"]})
    player["energyField"].append(entry)
    player["energyPlays"] = player.get("energyPlays", 0) + 1

    if face_up:
        msg = f"plays {played['id']} face up as energy"
        if swapped:
            msg += " and swaps an energy card back to hand"
    else:
        # face-down energy is hidden information: never name it in the log
        msg = "places a card face down as energy"
    log(state, msg, player)
    return state


def ready_energy(player: dict, uids) -> tuple[list[dict], str | None]:
    """Resolve `uids` to the player's ready energy cards, in order. Returns
    (cards, None), or ([], error) when any uid is missing, repeated, not in
    the energy field, or already resting — payments never partially apply."""
    field = {c["uid"]: c for c in player["energyField"]}
    if (
        not isinstance(uids, list)
        or len(set(uids)) != len(uids)
        or not set(uids) <= field.keys()
    ):
        return [], "Those cards are not in your energy field"
    cards = [field[uid] for uid in uids]
    if any(card.get("resting") for card in cards):
        return [], "Resting energy is already spent until your upkeep"
    return cards, None


def rest_energy(state: dict, player: dict, data, pool=None) -> dict:
    """Rest chosen ready energy cards to pay a cost (rulebook pp. 12, 15, 17):
    resting is how energy is spent, one 💠 per card. Allowed on either
    player's turn — costs come up whenever something is cast, including
    abilities on the opponent's turn — and the cards ready again in the
    owner's upkeep. `data` is the list of energy uids to rest; `pool` is
    unused, part of the uniform game-action signature."""
    if state.get("phase") != "main":
        return {"error": "Energy can only be rested while the game is in play"}
    cards, error = ready_energy(player, data)
    if error or not cards:
        return {"error": error or "Choose at least one energy card to rest"}
    for card in cards:
        card["resting"] = True
    log(state, f"rests {len(cards)} energy card{'' if len(cards) == 1 else 's'}", player)
    return state


def generate_resources(player: dict, count: int) -> int:
    """Generate resources (rulebook p. 12): move up to `count` resource cards
    deck -> field. Generate instructions are ignored once the resource deck is
    empty, so the return value is how many actually moved."""
    moved = min(count, player["resourceDeck"])
    player["resourceDeck"] -= moved
    player["resourceField"] += moved
    return moved


def spend_resources(player: dict, count: int) -> bool:
    """Pay `count` resources, returning them field -> deck (p. 12). False
    (and nothing moves) when the player doesn't have that many."""
    if player["resourceField"] < count:
        return False
    player["resourceField"] -= count
    player["resourceDeck"] += count
    return True


def conversion_cost(player: dict, pool: dict[str, Card]) -> int | None:
    """The commander's energy -> resource conversion rate, read like
    energy_limit: current evolution stage first, falling back through earlier
    stages when a stage's Studio cell is still unset."""
    stages = player["commander"]["stages"][: player["commander"]["stage"] + 1]
    for stage_id in reversed(stages):
        card = pool.get(stage_id)
        if card and card.conversion_cost is not None:
            return card.conversion_cost
    return None


def convert_energy(state: dict, player: dict, data, pool: dict[str, Card]) -> dict:
    """Convert energy into a resource (rulebook p. 12): rest ready energy
    equal to the commander's conversion rate to generate 1 resource. Allowed
    at any time, on either player's turn — even during upkeep — so like
    rest_energy there is no turn check. `data` is the list of energy uids to
    rest as the payment."""
    if state.get("phase") != "main":
        return {"error": "Energy can only be converted while the game is in play"}
    cost = conversion_cost(player, pool)
    if cost is None:
        return {"error": "Your commander has no conversion rate in the card pool"}
    if player["resourceDeck"] < 1:
        return {"error": "Your resource deck is empty — no resources left to generate"}
    payment, error = ready_energy(player, data)
    if error:
        return {"error": error}
    if len(payment) != cost:
        return {"error": f"Converting takes exactly {cost} energy for 1 {player['resource']}"}
    for energy in payment:
        energy["resting"] = True
    generate_resources(player, 1)
    log(state, f"converts {cost} energy into 1 {player['resource']}", player)
    return state


def cast_reserve(state: dict, player: dict, data, pool: dict[str, Card]) -> dict:
    """Cast a reserve card (rulebook pp. 9-10, 18): paid in resources, not
    energy; once per round; never before your second turn (both players'
    second turns fall in round 2). A Weapon or Armor enters the equipment
    area and Removes the previous one of its type, a Battlefield likewise
    replaces the battlefield, and a Feat resolves (effects stay manual until
    the skills engine lands) and is then Removed. `data` is {"uid": the
    reserve card to cast}."""
    if state.get("phase") != "main":
        return {"error": "Reserve cards can only be cast in your main phase"}
    if state["players"][state["activePlayer"]] is not player:
        return {"error": "It is not your turn"}
    if state["round"] < RESERVE_UNLOCK_ROUND:
        return {"error": "Reserve cards can't be cast until your second turn"}
    # .get: games started before the counter existed have no reserveCasts key
    if player.get("reserveCasts", 0) >= RESERVE_CASTS_PER_ROUND:
        return {"error": "You have already cast a reserve card this round"}
    data = data if isinstance(data, dict) else {}

    played = next((c for c in player["reserve"] if c["uid"] == data.get("uid")), None)
    if not played:
        return {"error": "That card is not in your reserve deck"}
    card = pool.get(played["id"])
    slot = card.reserve_type if card else None
    if not slot:
        return {"error": f"{played['id']} is not a typed reserve card in the card pool"}
    if card.cost is None:
        return {"error": f"{card.id} has no cost in the card pool"}
    if not spend_resources(player, card.cost):
        return {
            "error": f"{card.id} costs {card.cost} {player['resource']}"
            f" — you have {player['resourceField']}"
        }

    player["reserve"] = [c for c in player["reserve"] if c["uid"] != played["uid"]]
    removed = player.setdefault("removed", [])
    entry = {"id": played["id"], "uid": played["uid"], "slot": slot.value, "resting": False}
    replaced = None
    if slot == ReserveType.FEAT:
        removed.append({"id": played["id"], "uid": played["uid"]})
    elif slot == ReserveType.BATTLEFIELD:
        replaced, player["battlefield"] = player["battlefield"], entry
    else:  # Weapon / Armor share the equipment area, one active of each type
        replaced = next((c for c in player["equipment"] if c.get("slot") == slot.value), None)
        player["equipment"] = [c for c in player["equipment"] if c is not replaced] + [entry]
    if replaced:
        removed.append({"id": replaced["id"], "uid": replaced["uid"]})
    player["reserveCasts"] = player.get("reserveCasts", 0) + 1

    spent = f", spending {card.cost} {player['resource']}" if card.cost else ""
    msg = f"casts {played['id']} from their reserve{spent}"
    if replaced:
        msg += f", removing {replaced['id']} from the game"
    log(state, msg, player)
    return state


def cast_card(state: dict, player: dict, data, pool: dict[str, Card]) -> dict:
    """Cast a unit or spell from hand (rulebook pp. 17-18): pay its cost by
    resting exactly that many ready energy cards, then resolve. A unit joins
    the battleground (up to the capacity of 5) with summoning sickness until
    the owner's next upkeep, tracked as `enteredThisRound`; a spell resolves
    and goes to the discard pile (card effects stay manual until the skills
    engine lands). Main phase, your turn only — abilities and reserve cards
    have their own timing and are separate actions. `data` is
    {"uid": hand card, "energy": [energy uids to rest]}."""
    if state.get("phase") != "main":
        return {"error": "Units and spells can only be cast in your main phase"}
    if state["players"][state["activePlayer"]] is not player:
        return {"error": "It is not your turn"}
    data = data if isinstance(data, dict) else {}

    played = next((c for c in player["hand"] if c["uid"] == data.get("uid")), None)
    if not played:
        return {"error": "That card is not in your hand"}
    card = pool.get(played["id"])
    if not card:
        return {"error": f"{played['id']} is missing from the card pool"}
    if card.card_type == CardType.CORE:
        return {"error": "Artifact Cores are never cast — place them as energy instead"}
    if card.card_type not in (CardType.UNIT, CardType.SPELL):
        return {"error": "Only units and spells can be cast from your hand"}
    if card.cost is None:
        return {"error": f"{card.id} has no cost in the card pool"}
    if card.is_unit and len(player["battleground"]) >= BATTLEGROUND_CAPACITY:
        return {"error": f"Your battleground is full ({BATTLEGROUND_CAPACITY} units)"}

    payment, error = ready_energy(player, data.get("energy") or [])
    if error:
        return {"error": error}
    if len(payment) != card.cost:
        return {"error": f"{card.id} costs {card.cost} — rest exactly that much energy"}

    for energy in payment:
        energy["resting"] = True
    player["hand"] = [c for c in player["hand"] if c["uid"] != played["uid"]]
    if card.is_unit:
        player["battleground"].append({
            "id": played["id"],
            "uid": played["uid"],
            "resting": False,
            "enteredThisRound": True,  # summoning sickness (p. 21)
        })
    else:
        player["discard"].append({"id": played["id"], "uid": played["uid"]})
    rested = f", resting {card.cost} energy" if card.cost else ""
    log(state, f"casts {played['id']}{rested}", player)
    return state


def ready_all(player: dict):
    """Upkeep readying (rulebook p. 14): every resting card turns upright —
    energy, battleground units, equipment, the battlefield and reserves."""
    battlefield = [player["battlefield"]] if player["battlefield"] else []
    zones = [player["energyField"], player["battleground"], player["equipment"],
             player["reserve"], battlefield]
    for zone in zones:
        for card in zone:
            card["resting"] = False


def end_turn(state: dict, player: dict, data=None, pool=None) -> dict:
    """End the active player's turn (rulebook p. 14). Play passes to the
    opponent, whose upkeep readies all their cards and resets their energy
    allowance for the turn, followed by their 2-card draw phase; the round
    advances once the turn comes back around to the first player. Being
    unable to complete the draw loses the game on the spot (p. 11). `data`
    is unused; it's part of the uniform game-action signature."""
    if state.get("phase") != "main":
        return {"error": "You can only end your turn in your main phase"}
    if state["players"][state["activePlayer"]] is not player:
        return {"error": "It is not your turn"}

    log(state, "ends their turn", player)
    state["activePlayer"] = (state["activePlayer"] + 1) % len(state["players"])
    if state["activePlayer"] == state["firstPlayer"]:
        state["round"] += 1
        log(state, f"Round {state['round']}")

    upkeep = state["players"][state["activePlayer"]]
    ready_all(upkeep)
    for card in upkeep["battleground"]:
        card["enteredThisRound"] = False  # summoning sickness wears off
    upkeep["energyPlays"] = 0
    upkeep["reserveCasts"] = 0
    drawn = draw(upkeep, TURN_DRAW)
    log(state, f"draws {drawn} card{'' if drawn == 1 else 's'}", upkeep)
    if drawn < TURN_DRAW:
        # "instructed to draw a card but their deck is empty" — they lose
        state["phase"] = "over"
        state["winner"] = state["players"].index(player)
        log(state, "runs out of cards to draw", upkeep)
        log(state, f"{player['user']['username']} wins the game")
    return state

"""In-game turn actions, growing alongside game_setup.py the way uprising's
game.py does. Every action shares the (state, player, data, pool) signature
used by main.GAME_ACTIONS: mutate the state dict in place and return it, or
return {"error": ...} without touching anything.
"""

from .game_setup import log
from .models import Card, CardType
from .rules import ENERGY_PLAYS_PER_TURN, FIRST_TURN_ENERGY_PLAYS


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

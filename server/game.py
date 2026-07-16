"""In-game turn actions, growing alongside game_setup.py the way uprising's
game.py does. Every action shares the (state, player, data, pool) signature
used by main.GAME_ACTIONS: mutate the state dict in place and return it, or
return {"error": ...} without touching anything.
"""

from .game_setup import draw, log
from .models import Card, CardType
from .rules import ENERGY_PLAYS_PER_TURN, FIRST_TURN_ENERGY_PLAYS, TURN_DRAW


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


def rest_energy(state: dict, player: dict, data, pool=None) -> dict:
    """Rest chosen ready energy cards to pay a cost (rulebook pp. 12, 15, 17):
    resting is how energy is spent, one 💠 per card. Allowed on either
    player's turn — costs come up whenever something is cast, including
    abilities on the opponent's turn — and the cards ready again in the
    owner's upkeep. `data` is the list of energy uids to rest; `pool` is
    unused, part of the uniform game-action signature."""
    if state.get("phase") != "main":
        return {"error": "Energy can only be rested while the game is in play"}
    uids = data if isinstance(data, list) else []
    field = {c["uid"]: c for c in player["energyField"]}
    if not uids or len(set(uids)) != len(uids) or not set(uids) <= field.keys():
        return {"error": "Those cards are not in your energy field"}
    if any(field[uid].get("resting") for uid in uids):
        return {"error": "Resting energy is already spent until your upkeep"}
    for uid in uids:
        field[uid]["resting"] = True
    count = len(uids)
    log(state, f"rests {count} energy card{'' if count == 1 else 's'}", player)
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
        log(state, f"Round {state['round']} begins")

    upkeep = state["players"][state["activePlayer"]]
    ready_all(upkeep)
    upkeep["energyPlays"] = 0
    drawn = draw(upkeep, TURN_DRAW)
    log(state, f"draws {drawn} card{'' if drawn == 1 else 's'}", upkeep)
    if drawn < TURN_DRAW:
        # "instructed to draw a card but their deck is empty" — they lose
        state["phase"] = "over"
        state["winner"] = state["players"].index(player)
        log(state, "runs out of cards to draw", upkeep)
        log(state, f"{player['user']['username']} wins the game")
    return state

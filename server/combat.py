"""Combat (rulebook pp. 21-24): declaring attacks, the six combat steps,
damage shields, combat keywords, KOs and commander evolution (p. 11).

A running combat is its own phase (state["phase"] = "combat") with an
explicit sub-state at state["combat"]:

    {
        "step": "preDefender" | "defender" | "postDefender" | "endOfCombat",
        "attackingPlayer": seat index,
        "attacker": the attacker's battleground uid, or "commander",
        "target": the defender's battleground uid, or "commander",
        "attackBonus": int,      # Duelist's +Atk this combat
        "shields": [BoardCard],  # hand cards played as damage shields
        "passed": [seat indexes done with the current step],
    }

Of the rulebook's six steps, Declare Attack resolves inside declare_attack
and Combat Damage resolves the moment Post-Defender ends (players can't act
in either, p. 22), so only the four windows in between exist as `step`
values. In a window players act — rest/convert energy, play shields,
Intercept — and pass; a step advances when everyone who may act has passed
(both players, except the Defender step which is the defender's alone), and
playing a shield reopens the window. Skills and triggers (ON ATTACK,
DEFENDER, END OF COMBAT, ON KO) stay manual until the Milestone 4 engine,
but the windows they will fill already exist.

Keywords are parsed from rules text (Card.keyword_value); until the skills
engine lands only the combatant's own printed keywords count — equipment or
effects granting keywords aren't seen. Units leave play here only by KO,
which is deliberately its own helper: Destroy, Sacrifice and Remove are
different departures (p. 24) and only a KO will fire ON KO triggers.
"""

from .game import generate_resources, stage_stat
from .game_setup import draw, log
from .models import Card
from .rules import ATTACK_UNLOCK_ROUND

COMMANDER = "commander"  # attacker/target sentinel: the seat's commander

STEP_AFTER = {"preDefender": "defender", "defender": "postDefender"}


def stage_card(player: dict, pool: dict[str, Card]) -> Card | None:
    """The commander card itself for the current evolution stage — the
    latest stage present in the pool (unlike stage_stat, text isn't
    inherited cell-by-cell: a present card's keywords are its own)."""
    stages = player["commander"]["stages"][: player["commander"]["stage"] + 1]
    return next((pool[s] for s in reversed(stages) if s in pool), None)


def has_keyword(card: Card | None, keyword: str) -> bool:
    return card is not None and card.keyword_value(keyword) is not None


def keyword_value(card: Card | None, keyword: str) -> int:
    return (card.keyword_value(keyword) or 0) if card else 0


def seat_index(state: dict, player: dict) -> int:
    return next(i for i, p in enumerate(state["players"]) if p is player)


def combatant_name(seat: dict, pool: dict[str, Card], uid: str) -> str:
    if uid == COMMANDER:
        card = stage_card(seat, pool)
        return card.id if card else "their commander"
    return next((c["id"] for c in seat["battleground"] if c["uid"] == uid), "a unit")


def attackable_while_ready(attacker: Card | None, target: Card | None) -> bool:
    """Whether a *ready* unit is a legal target (p. 24): Heavy on the target
    or Initiative on the attacker overrides the resting rule, and a Scout
    attacker may attack ready Stealth units."""
    return (
        has_keyword(target, "Heavy")
        or has_keyword(attacker, "Initiative")
        or (has_keyword(attacker, "Scout") and has_keyword(target, "Stealth"))
    )


def declare_attack(state: dict, player: dict, data, pool: dict[str, Card]) -> dict:
    """Declare an attack (p. 21): rest your ready commander or a ready,
    non-summoning-sick unit (Haste ignores sickness) against the enemy
    commander (always attackable) or a resting enemy unit. Any number of
    combats per turn, one at a time, never in round 1. Conjure and Duelist
    resolve as part of the declaration. `data` is {"attacker", "target"},
    each a battleground uid or "commander"."""
    if state.get("phase") != "main":
        return {"error": "Attacks are declared from your main phase"}
    if state["players"][state["activePlayer"]] is not player:
        return {"error": "It is not your turn"}
    if state["round"] < ATTACK_UNLOCK_ROUND:
        return {"error": "Nothing can attack on the game's first round"}
    data = data if isinstance(data, dict) else {}
    attacker_uid, target_uid = data.get("attacker"), data.get("target")
    defender = state["players"][1 - seat_index(state, player)]  # two-player duel

    attacker = None
    if attacker_uid == COMMANDER:
        if player["commander"].get("resting"):
            return {"error": "Your commander is resting"}
        attacker_card = stage_card(player, pool)
    else:
        attacker = next((c for c in player["battleground"] if c["uid"] == attacker_uid), None)
        if not attacker:
            return {"error": "That attacker is not on your battleground"}
        if attacker.get("resting"):
            return {"error": f"{attacker['id']} is resting"}
        attacker_card = pool.get(attacker["id"])
        if attacker.get("enteredThisRound") and not has_keyword(attacker_card, "Haste"):
            return {"error": f"{attacker['id']} entered this round and can't attack yet"}
    if attacker_card is None:
        return {"error": "The attacker is missing from the card pool"}

    target = None
    if target_uid != COMMANDER:
        target = next((c for c in defender["battleground"] if c["uid"] == target_uid), None)
        if not target:
            return {"error": "That target is not on your opponent's battleground"}
        target_card = pool.get(target["id"])
        if not target.get("resting") and not attackable_while_ready(attacker_card, target_card):
            return {"error": f"{target['id']} is ready and can't be attacked"}
    # Taunt (p. 24): a resting Taunt unit forces itself as the target —
    # unless the attacker has Stealth, which ignores Taunt entirely.
    if not has_keyword(attacker_card, "Stealth"):
        taunters = [
            c for c in defender["battleground"]
            if c.get("resting") and has_keyword(pool.get(c["id"]), "Taunt")
        ]
        if taunters and target not in taunters:
            return {"error": f"A resting unit with Taunt must be attacked: {taunters[0]['id']}"}

    if attacker:
        attacker["resting"] = True
    else:
        player["commander"]["resting"] = True
    state["phase"] = "combat"
    state["combat"] = {
        "step": "preDefender",
        "attackingPlayer": seat_index(state, player),
        "attacker": attacker_uid,
        "target": target_uid,
        "attackBonus": 0,
        "shields": [],
        "passed": [],
    }
    target_name = combatant_name(defender, pool, target_uid)
    log(state, f"attacks {target_name} with {attacker_card.id}", player)

    # Conjure (p. 24): the attacker generates resources as it attacks — not
    # optional and not a trigger (silently ignored on an empty resource deck).
    if conjure := keyword_value(attacker_card, "Conjure"):
        if moved := generate_resources(player, conjure):
            log(state, f"conjures {moved} {player['resource']}", player)
    # Duelist (p. 24): +Atk this combat equal to the top discard's Shield
    # Power; that card goes to the bottom of the deck. Not optional.
    if has_keyword(attacker_card, "Duelist") and player["discard"]:
        top = player["discard"].pop()
        top_card = pool.get(top["id"])
        bonus = (top_card.shield_power or 0) if top_card else 0
        state["combat"]["attackBonus"] = bonus
        player["deck"].append(top)  # index 0 is the top, so the end is the bottom
        log(state, f"bottoms {top['id']} for Duelist: +{bonus} Atk this combat", player)
    return state


def combat_guard(state: dict, player: dict) -> tuple[dict | None, int, str | None]:
    """(combat sub-state, the player's seat index, error)."""
    if state.get("phase") != "combat" or not state.get("combat"):
        return None, 0, "No combat is underway"
    return state["combat"], seat_index(state, player), None


def victim_shield_capacity(defender: dict, combat: dict, pool: dict[str, Card]) -> int:
    if combat["target"] == COMMANDER:
        return stage_stat(defender, pool, "shield_capacity") or 0
    card = next((c for c in defender["battleground"] if c["uid"] == combat["target"]), None)
    pool_card = pool.get(card["id"]) if card else None
    return (pool_card.shield_capacity or 0) if pool_card else 0


def play_shield(state: dict, player: dict, data, pool: dict[str, Card]) -> dict:
    """Play a hand card as a damage shield (p. 23): the victim's controller
    only, in the Pre- or Post-Defender step (the Defender step is reserved
    for Defender-step skills, and nobody acts at Combat Damage). Up to the
    victim's Shield Capacity cards per damage instance; each will shield its
    Shield Power when the damage resolves and is then discarded. `data` is
    {"uid": the hand card}."""
    combat, idx, error = combat_guard(state, player)
    if error:
        return {"error": error}
    if combat["step"] not in ("preDefender", "postDefender"):
        return {"error": "Shields are played in the Pre- or Post-Defender step"}
    if idx == combat["attackingPlayer"]:
        return {"error": "Only the player being attacked plays damage shields"}
    data = data if isinstance(data, dict) else {}
    card = next((c for c in player["hand"] if c["uid"] == data.get("uid")), None)
    if not card:
        return {"error": "That card is not in your hand"}
    capacity = victim_shield_capacity(player, combat, pool)
    if len(combat["shields"]) >= capacity:
        return {"error": f"The victim's Shield Capacity is {capacity} per instance of damage"}

    player["hand"] = [c for c in player["hand"] if c["uid"] != card["uid"]]
    combat["shields"].append({"id": card["id"], "uid": card["uid"]})
    combat["passed"] = []  # a new shield reopens the response window
    pool_card = pool.get(card["id"])
    power = (pool_card.shield_power or 0) if pool_card else 0
    log(state, f"plays {card['id']} as a damage shield (Shield Power {power})", player)
    return state


def intercept(state: dict, player: dict, data, pool: dict[str, Card]) -> dict:
    """Rest a unit with Intercept to redirect the incoming attack onto it
    (p. 24): Defender step only, usable through summoning sickness, blocked
    by a Stealth attacker. The redirected attack is a new instance of
    damage, so shields already played are wasted (discarded shielding
    nothing). `data` is {"uid": your Intercept unit}."""
    combat, idx, error = combat_guard(state, player)
    if error:
        return {"error": error}
    if combat["step"] != "defender":
        return {"error": "Intercepting happens in the Defender step"}
    if idx == combat["attackingPlayer"]:
        return {"error": "Only the defending player can intercept"}
    data = data if isinstance(data, dict) else {}
    unit = next((c for c in player["battleground"] if c["uid"] == data.get("uid")), None)
    if not unit:
        return {"error": "That unit is not on your battleground"}
    if not has_keyword(pool.get(unit["id"]), "Intercept"):
        return {"error": f"{unit['id']} does not have Intercept"}
    if unit["uid"] == combat["target"]:
        return {"error": f"{unit['id']} is already the target"}
    if unit.get("resting"):
        return {"error": f"{unit['id']} is resting and can't be rested to intercept"}
    attacker_seat = state["players"][combat["attackingPlayer"]]
    attacker_card = combatant_card(attacker_seat, pool, combat["attacker"])
    if has_keyword(attacker_card, "Stealth"):
        return {"error": "A Stealth attacker can't be intercepted"}

    unit["resting"] = True
    combat["target"] = unit["uid"]
    # wasted shields: the prevention applied to the original instance
    player["discard"] += [{"id": s["id"], "uid": s["uid"]} for s in combat["shields"]]
    combat["shields"] = []
    log(state, f"rests {unit['id']} to intercept the attack", player)
    return state


def pass_combat(state: dict, player: dict, data, pool: dict[str, Card]) -> dict:
    """Pass on the current combat step. Pre-Defender, Post-Defender and End
    of Combat advance once both players have passed; the Defender step is
    the defender's alone (the attacker can't act in it, p. 22), so their
    single pass advances it. Ending Post-Defender resolves the attack damage
    immediately. `data` is unused."""
    combat, idx, error = combat_guard(state, player)
    if error:
        return {"error": error}
    if combat["step"] == "defender":
        if idx == combat["attackingPlayer"]:
            return {"error": "The attacking player can't act in the Defender step"}
    else:
        if idx in combat["passed"]:
            return {"error": "You have already passed this step"}
        combat["passed"].append(idx)
        if len(combat["passed"]) < len(state["players"]):
            return state

    combat["passed"] = []
    if next_step := STEP_AFTER.get(combat["step"]):
        combat["step"] = next_step
    elif combat["step"] == "postDefender":
        resolve_damage(state, pool)
        if state["phase"] == "over":
            state.pop("combat", None)
        else:
            combat["step"] = "endOfCombat"
    else:  # endOfCombat: the combat is over, back to a main phase
        state.pop("combat", None)
        state["phase"] = "main"
        log(state, "End of combat")
    return state


def combatant_card(seat: dict, pool: dict[str, Card], uid: str) -> Card | None:
    if uid == COMMANDER:
        return stage_card(seat, pool)
    entry = next((c for c in seat["battleground"] if c["uid"] == uid), None)
    return pool.get(entry["id"]) if entry else None


def resolve_damage(state: dict, pool: dict[str, Card]):
    """The Combat Damage step (pp. 21-23), resolved without input: attack
    damage is the attacker's Atk (plus any Duelist bonus), less the played
    shields' total Shield Power (Piercing N ignores the first N points),
    less the victim's Armor. A commander victim loses that much HP; a unit
    victim is KO'd iff the damage reaches its Health, and otherwise takes
    nothing (damage never accumulates). Riposte strikes back at the same
    time as the attack damage."""
    combat = state["combat"]
    attacker_seat = state["players"][combat["attackingPlayer"]]
    defender_seat = state["players"][1 - combat["attackingPlayer"]]
    attacker_card = combatant_card(attacker_seat, pool, combat["attacker"])
    victim_card = combatant_card(defender_seat, pool, combat["target"])
    attacker_name = combatant_name(attacker_seat, pool, combat["attacker"])

    if combat["attacker"] == COMMANDER:
        atk = stage_stat(attacker_seat, pool, "attack") or 0
    else:
        atk = (attacker_card.attack or 0) if attacker_card else 0
    atk += combat["attackBonus"]

    # Shields block their combined Shield Power, less the attacker's Piercing,
    # and are spent to the discard pile either way.
    shield_power = sum(
        (card.shield_power or 0) if (card := pool.get(s["id"])) else 0
        for s in combat["shields"]
    )
    blocked = max(0, shield_power - keyword_value(attacker_card, "Piercing"))
    defender_seat["discard"] += [{"id": s["id"], "uid": s["uid"]} for s in combat["shields"]]
    combat["shields"] = []

    # Armor is flat damage reduction on the victim, applied to any damage.
    if combat["target"] == COMMANDER:
        armor = keyword_value(stage_card(defender_seat, pool), "Armor")
    else:
        armor = keyword_value(victim_card, "Armor")
    damage = max(0, atk - blocked - armor)

    if combat["target"] == COMMANDER:
        who = defender_seat["user"]["username"]
        log(state, f"{attacker_name} deals {damage} damage to {who}'s commander")
        damage_commander(state, defender_seat, damage, pool)
    else:
        victim = next(c for c in defender_seat["battleground"] if c["uid"] == combat["target"])
        health = victim_card.health if victim_card else None
        if health is not None and damage >= health:
            log(state, f"{attacker_name} deals {damage} damage to {victim['id']}")
            ko_unit(state, defender_seat, victim)
        else:
            log(state, f"{attacker_name} deals {damage} damage to {victim['id']}, which survives")
        # Riposte (p. 24): the attacked unit hits back as the damage is
        # dealt — even if it was KO'd — and it isn't attack damage.
        if has_keyword(victim_card, "Riposte"):
            riposte_damage(state, combat, attacker_seat, victim["id"],
                           victim_card.attack or 0, pool)


def riposte_damage(state: dict, combat: dict, attacker_seat: dict, victim_id: str,
                   amount: int, pool: dict[str, Card]):
    attacker_card = combatant_card(attacker_seat, pool, combat["attacker"])
    amount = max(0, amount - keyword_value(attacker_card, "Armor"))
    attacker_name = combatant_name(attacker_seat, pool, combat["attacker"])
    log(state, f"{victim_id} ripostes for {amount} damage to {attacker_name}")
    if combat["attacker"] == COMMANDER:
        damage_commander(state, attacker_seat, amount, pool)
        return
    attacker = next((c for c in attacker_seat["battleground"] if c["uid"] == combat["attacker"]), None)
    health = attacker_card.health if attacker_card else None
    if attacker and health is not None and amount >= health:
        ko_unit(state, attacker_seat, attacker)


def ko_unit(state: dict, controller: dict, unit: dict):
    """KO (p. 21): the unit goes to its controller's discard pile. Kept
    distinct from Destroy / Sacrifice / Remove (p. 24) — only a KO will fire
    ON KO triggers once the skills engine lands."""
    controller["battleground"] = [c for c in controller["battleground"] if c is not unit]
    controller["discard"].append({"id": unit["id"], "uid": unit["uid"]})
    log(state, f"{unit['id']} is KO'd")


def damage_commander(state: dict, player: dict, amount: int, pool: dict[str, Card]):
    """Commander damage and evolution (p. 11): at 0 HP the commander evolves
    — HP resets to the new stage's max (excess damage does not carry over),
    draw 1 card, generate 1 resource — and a commander with no evolutions
    left loses the game. The evolution draw is a real draw: an empty deck
    there is the deck-out loss."""
    if amount <= 0:
        return
    player["hp"] -= amount
    if player["hp"] > 0:
        return
    commander = player["commander"]
    if commander["stage"] + 1 >= len(commander["stages"]):
        player["hp"] = 0
        log(state, "has no evolutions left", player)
        lose_game(state, player)
        return
    commander["stage"] += 1
    stage_id = commander["stages"][commander["stage"]]
    player["maxHp"] = stage_stat(player, pool, "hp") or player["maxHp"]
    player["hp"] = player["maxHp"]
    generate_resources(player, 1)
    log(state, f"evolves their commander into {stage_id}", player)
    if draw(player, 1) < 1:
        log(state, "runs out of cards to draw", player)
        lose_game(state, player)


def lose_game(state: dict, loser: dict):
    state["phase"] = "over"
    state["winner"] = 1 - seat_index(state, loser)
    winner = state["players"][state["winner"]]
    log(state, f"{winner['user']['username']} wins the game")

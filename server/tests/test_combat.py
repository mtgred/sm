"""Combat tests (rulebook pp. 21-24): attack declaration and legality, the
combat-step windows, damage shields, keywords, KOs and commander evolution
(p. 11).

They run over the conftest pool: Keshi Savageclaw (Base) has Atk 4, Shield
Capacity 1, HP 10, "Conjure (💠)" and a single further evolution stage whose
cells are all unset (stat lookups fall back to Base); Common Unit is a 2/2
with Shield Capacity 1 / Shield Power 1; Common Spell has Shield Power 2;
and there is one unit per combat keyword.
"""

import pytest
from fastapi.testclient import TestClient

from .. import main
from ..combat import (
    COMMANDER,
    declare_attack,
    intercept,
    pass_combat,
    play_shield,
)
from ..game import cast_card, end_turn, rest_energy
from ..main import app
from ..models import Card
from .test_game import energy, hand_card, main_phase_state
from .test_game_setup import game_post, started_game
from .test_lobby import ALICE, BOB, FakeDb


def unit(card_id: str, uid: str, resting=False, entered=False) -> dict:
    return {"id": card_id, "uid": uid, "resting": resting, "enteredThisRound": entered}


def combat_ready(pool, round=2) -> tuple[dict, dict, dict]:
    """A game in its main phase, past round 1's attack lockout by default:
    (state, active player, defending opponent)."""
    state, active = main_phase_state(pool)
    state["round"] = round
    return state, active, state["players"][1 - state["activePlayer"]]


def attack(state, player, attacker, target, pool):
    return declare_attack(state, player, {"attacker": attacker, "target": target}, pool)


def start_combat(pool, attacker_id="Common Unit", target=COMMANDER):
    """A declared attack by a planted unit, sitting at Pre-Defender."""
    state, active, other = combat_ready(pool)
    active["battleground"] = [unit(attacker_id, "a0")]
    assert "error" not in attack(state, active, "a0", target, pool)
    return state, active, other


def pass_step(state, pool):
    """Advance past the current step: the defender passes alone in the
    Defender step, both players everywhere else."""
    combat = state["combat"]
    attacker_seat = state["players"][combat["attackingPlayer"]]
    defender_seat = state["players"][1 - combat["attackingPlayer"]]
    if combat["step"] != "defender":
        assert "error" not in pass_combat(state, attacker_seat, None, pool)
    assert "error" not in pass_combat(state, defender_seat, None, pool)


def run_to_damage(state, pool):
    """Pass every window up to and including the damage resolution."""
    for _ in range(3):  # preDefender, defender, postDefender
        pass_step(state, pool)


# -- Declaring attacks (rulebook p. 21) ----------------------------------------


def test_declare_attack_opens_combat_and_rests_the_attacker(pool):
    state, active, other = combat_ready(pool)
    active["battleground"] = [unit("Common Unit", "a0")]
    assert attack(state, active, "a0", COMMANDER, pool) is state
    assert state["phase"] == "combat"
    assert state["combat"] == {
        "step": "preDefender",
        "attackingPlayer": state["activePlayer"],
        "attacker": "a0",
        "target": COMMANDER,
        "attackBonus": 0,
        "shields": [],
        "passed": [],
    }
    assert active["battleground"][0]["resting"] is True
    assert "attacks Keshi Savageclaw (Base) with Common Unit" in state["log"][-1]["msg"]


def test_commander_attack_rests_it_and_conjures(pool):
    state, active, other = combat_ready(pool)
    assert "error" not in attack(state, active, COMMANDER, COMMANDER, pool)
    assert active["commander"]["resting"] is True
    # Keshi's "Conjure (💠)": 1 resource generated as it attacks
    assert active["resourceField"] == 1 and active["resourceDeck"] == 3


def test_nothing_attacks_in_round_one(pool):
    state, active, other = combat_ready(pool, round=1)
    active["battleground"] = [unit("Haste Unit", "a0")]
    assert "error" in attack(state, active, "a0", COMMANDER, pool)
    assert "error" in attack(state, active, COMMANDER, COMMANDER, pool)


def test_summoning_sickness_blocks_attacks_but_not_haste(pool):
    state, active, other = combat_ready(pool)
    active["battleground"] = [
        unit("Common Unit", "a0", entered=True),
        unit("Haste Unit", "a1", entered=True),
    ]
    assert "error" in attack(state, active, "a0", COMMANDER, pool)
    assert "error" not in attack(state, active, "a1", COMMANDER, pool)


def test_ready_units_cannot_be_attacked(pool):
    state, active, other = combat_ready(pool)
    active["battleground"] = [unit("Common Unit", "a0")]
    other["battleground"] = [unit("Common Unit", "t0")]
    assert "error" in attack(state, active, "a0", "t0", pool)
    other["battleground"][0]["resting"] = True
    assert "error" not in attack(state, active, "a0", "t0", pool)


def test_heavy_targets_are_attackable_while_ready(pool):
    state, active, other = combat_ready(pool)
    active["battleground"] = [unit("Common Unit", "a0")]
    other["battleground"] = [unit("Heavy Unit", "t0")]
    assert "error" not in attack(state, active, "a0", "t0", pool)


def test_initiative_attacks_ready_units(pool):
    state, active, other = combat_ready(pool)
    active["battleground"] = [unit("Initiative Unit", "a0")]
    other["battleground"] = [unit("Common Unit", "t0")]
    assert "error" not in attack(state, active, "a0", "t0", pool)


def test_scout_attacks_ready_stealth_units_only(pool):
    state, active, other = combat_ready(pool)
    active["battleground"] = [unit("Scout Unit", "a0")]
    other["battleground"] = [unit("Common Unit", "t0"), unit("Stealth Unit", "t1")]
    assert "error" in attack(state, active, "a0", "t0", pool)
    assert "error" not in attack(state, active, "a0", "t1", pool)


def test_taunt_forces_the_attack(pool):
    state, active, other = combat_ready(pool)
    active["battleground"] = [unit("Common Unit", "a0")]
    other["battleground"] = [
        unit("Taunt Unit", "t0", resting=True),
        unit("Common Unit", "t1", resting=True),
    ]
    assert "error" in attack(state, active, "a0", "t1", pool)
    assert "error" in attack(state, active, "a0", COMMANDER, pool)
    assert "error" not in attack(state, active, "a0", "t0", pool)


def test_ready_taunt_does_not_taunt(pool):
    state, active, other = combat_ready(pool)
    active["battleground"] = [unit("Common Unit", "a0")]
    other["battleground"] = [unit("Taunt Unit", "t0")]  # ready: Taunt is off
    assert "error" not in attack(state, active, "a0", COMMANDER, pool)


def test_stealth_ignores_taunt(pool):
    state, active, other = combat_ready(pool)
    active["battleground"] = [unit("Stealth Unit", "a0")]
    other["battleground"] = [unit("Taunt Unit", "t0", resting=True)]
    assert "error" not in attack(state, active, "a0", COMMANDER, pool)


def test_declare_attack_guards(pool):
    state, active, other = combat_ready(pool)
    active["battleground"] = [unit("Common Unit", "a0", resting=True), unit("Common Unit", "a1")]
    assert "error" in attack(state, active, "a0", COMMANDER, pool)  # resting attacker
    assert "error" in attack(state, active, "nope", COMMANDER, pool)
    assert "error" in attack(state, active, "a1", "nope", pool)
    active["commander"]["resting"] = True
    assert "error" in attack(state, active, COMMANDER, COMMANDER, pool)
    assert "error" in attack(state, other, COMMANDER, COMMANDER, pool)  # not your turn
    state["phase"] = "combat"  # one attack at a time
    assert "error" in attack(state, active, "a1", COMMANDER, pool)


# -- The combat steps (rulebook p. 22) -----------------------------------------


def test_steps_advance_to_damage_and_back_to_main(pool):
    state, active, other = start_combat(pool)  # Common Unit (Atk 2) vs commander
    hp = other["hp"]
    for step in ("defender", "postDefender"):
        pass_step(state, pool)
        assert state["combat"]["step"] == step
    pass_step(state, pool)  # ends Post-Defender: damage resolves
    assert other["hp"] == hp - 2
    assert state["combat"]["step"] == "endOfCombat"
    pass_step(state, pool)
    assert "combat" not in state and state["phase"] == "main"
    # attacks can keep coming, one combat at a time (the attacker is spent)
    assert "error" not in attack(state, active, COMMANDER, COMMANDER, pool)


def test_a_single_pass_waits_for_the_opponent(pool):
    state, active, other = start_combat(pool)
    assert "error" not in pass_combat(state, active, None, pool)
    assert state["combat"]["step"] == "preDefender"
    assert "error" in pass_combat(state, active, None, pool)  # double pass
    assert "error" not in pass_combat(state, other, None, pool)
    assert state["combat"]["step"] == "defender"


def test_the_attacker_cannot_act_in_the_defender_step(pool):
    state, active, other = start_combat(pool)
    pass_step(state, pool)
    assert "error" in pass_combat(state, active, None, pool)
    assert "error" in intercept(state, active, {"uid": "a0"}, pool)


def test_combat_blocks_casting_and_end_turn_but_not_energy(pool):
    state, active, other = start_combat(pool)
    card = hand_card(active, "Uncommon Unit")  # cost 0
    assert "error" in cast_card(state, active, {"uid": card["uid"]}, pool)
    assert "error" in end_turn(state, active, None, pool)
    other["energyField"] = [energy(uid="e0")]
    assert "error" not in rest_energy(state, other, ["e0"], pool)


def test_pass_outside_combat_is_rejected(pool):
    state, active, other = combat_ready(pool)
    assert "error" in pass_combat(state, active, None, pool)


# -- Attack damage and KOs (rulebook p. 21) ------------------------------------


def test_attack_damage_kos_a_unit(pool):
    state, active, other = combat_ready(pool)
    active["battleground"] = [unit("Common Unit", "a0")]  # Atk 2
    other["battleground"] = [unit("Haste Unit", "t0", resting=True)]  # Health 1
    attack(state, active, "a0", "t0", pool)
    run_to_damage(state, pool)
    assert other["battleground"] == []
    assert other["discard"][-1] == {"id": "Haste Unit", "uid": "t0"}
    assert state["log"][-1]["msg"] == "Haste Unit is KO'd"


def test_damage_below_health_does_nothing(pool):
    state, active, other = combat_ready(pool)
    active["battleground"] = [unit("Common Unit", "a0")]  # Atk 2
    other["battleground"] = [unit("Heavy Unit", "t0", resting=True)]  # Health 4
    attack(state, active, "a0", "t0", pool)
    run_to_damage(state, pool)
    # damage never accumulates: the unit is simply untouched
    assert other["battleground"] == [unit("Heavy Unit", "t0", resting=True)]


def test_armor_reduces_attack_damage(pool):
    state, active, other = combat_ready(pool)
    active["battleground"] = [unit("Common Unit", "a0")]  # Atk 2
    other["battleground"] = [unit("Armored Unit", "t0", resting=True)]  # Armor 2, Health 3
    attack(state, active, "a0", "t0", pool)
    run_to_damage(state, pool)
    assert "deals 0 damage" in state["log"][-1]["msg"]
    assert other["battleground"] != []


def test_riposte_strikes_back_as_damage_is_dealt(pool):
    state, active, other = combat_ready(pool)
    active["battleground"] = [unit("Common Unit", "a0")]  # 2/2
    other["battleground"] = [unit("Riposte Unit", "t0", resting=True)]  # 3/2
    attack(state, active, "a0", "t0", pool)
    run_to_damage(state, pool)
    # simultaneous: the victim is KO'd and still ripostes the attacker down
    assert other["battleground"] == [] and active["battleground"] == []
    assert other["discard"][-1]["id"] == "Riposte Unit"
    assert active["discard"][-1]["id"] == "Common Unit"


def test_duelist_gains_the_top_discards_shield_power(pool):
    state, active, other = combat_ready(pool)
    active["battleground"] = [unit("Duelist Unit", "a0")]  # Atk 2
    active["discard"] = [{"id": "Common Unit", "uid": "d0"}, {"id": "Common Spell", "uid": "d1"}]
    hp = other["hp"]
    attack(state, active, "a0", COMMANDER, pool)
    # the top discard (Shield Power 2) went to the bottom of the deck
    assert state["combat"]["attackBonus"] == 2
    assert active["discard"] == [{"id": "Common Unit", "uid": "d0"}]
    assert active["deck"][-1]["uid"] == "d1"
    run_to_damage(state, pool)
    assert other["hp"] == hp - 4


# -- Damage shields (rulebook p. 23) -------------------------------------------


def test_shields_block_their_power_and_are_discarded(pool):
    state, active, other = start_combat(pool)  # Atk 2 vs commander
    shield = hand_card(other, "Common Spell")  # Shield Power 2
    hp = other["hp"]
    assert "error" not in play_shield(state, other, {"uid": shield["uid"]}, pool)
    assert shield["uid"] not in [c["uid"] for c in other["hand"]]
    run_to_damage(state, pool)
    assert other["hp"] == hp  # fully blocked
    assert other["discard"][-1] == {"id": "Common Spell", "uid": shield["uid"]}


def test_shield_capacity_caps_each_damage_instance(pool):
    state, active, other = start_combat(pool)  # Keshi: Shield Capacity 1
    first, second = hand_card(other, "Common Spell"), hand_card(other, "Common Spell")
    assert "error" not in play_shield(state, other, {"uid": first["uid"]}, pool)
    assert "error" in play_shield(state, other, {"uid": second["uid"]}, pool)


def test_playing_a_shield_reopens_the_pass_window(pool):
    state, active, other = start_combat(pool)
    assert "error" not in pass_combat(state, active, None, pool)
    shield = hand_card(other, "Common Spell")
    play_shield(state, other, {"uid": shield["uid"]}, pool)
    assert state["combat"]["passed"] == []
    assert "error" not in pass_combat(state, active, None, pool)


def test_piercing_ignores_shield_points(pool):
    state, active, other = start_combat(pool, attacker_id="Piercing Unit")  # Atk 3, Piercing 2
    shield = hand_card(other, "Common Spell")  # Shield Power 2, fully pierced
    hp = other["hp"]
    play_shield(state, other, {"uid": shield["uid"]}, pool)
    run_to_damage(state, pool)
    assert other["hp"] == hp - 3


def test_shield_guards(pool):
    state, active, other = start_combat(pool)
    mine = hand_card(active, "Common Spell")
    assert "error" in play_shield(state, active, {"uid": mine["uid"]}, pool)  # attacker
    assert "error" in play_shield(state, other, {"uid": "not-in-hand"}, pool)
    pass_step(state, pool)  # Defender step: no shields
    shield = hand_card(other, "Common Spell")
    assert "error" in play_shield(state, other, {"uid": shield["uid"]}, pool)


# -- Intercept (rulebook p. 24) ------------------------------------------------


def test_intercept_redirects_and_wastes_played_shields(pool):
    state, active, other = start_combat(pool)  # Atk 2 vs commander
    other["battleground"] = [unit("Intercept Unit", "i0", entered=True)]  # Health 4
    shield = hand_card(other, "Common Spell")
    play_shield(state, other, {"uid": shield["uid"]}, pool)
    pass_step(state, pool)  # to the Defender step
    hp = other["hp"]
    assert "error" not in intercept(state, other, {"uid": "i0"}, pool)
    assert state["combat"]["target"] == "i0"
    assert other["battleground"][0]["resting"] is True
    # the redirected attack is a new damage instance: the shield was wasted
    assert state["combat"]["shields"] == []
    assert other["discard"][-1]["uid"] == shield["uid"]
    pass_step(state, pool)  # Defender again after the intercept
    pass_step(state, pool)  # Post-Defender -> damage
    assert other["hp"] == hp  # commander untouched
    assert other["battleground"] != []  # 2 damage < Health 4


def test_stealth_cannot_be_intercepted(pool):
    state, active, other = start_combat(pool, attacker_id="Stealth Unit")
    other["battleground"] = [unit("Intercept Unit", "i0")]
    pass_step(state, pool)
    assert "error" in intercept(state, other, {"uid": "i0"}, pool)


def test_intercept_guards(pool):
    state, active, other = start_combat(pool)
    other["battleground"] = [
        unit("Intercept Unit", "i0", resting=True),
        unit("Common Unit", "c0"),
    ]
    assert "error" in intercept(state, other, {"uid": "i0"}, pool)  # wrong step
    pass_step(state, pool)
    assert "error" in intercept(state, other, {"uid": "i0"}, pool)  # resting
    assert "error" in intercept(state, other, {"uid": "c0"}, pool)  # no Intercept
    assert "error" in intercept(state, other, {"uid": "nope"}, pool)


# -- Commander HP and evolution (rulebook p. 11) -------------------------------


def test_commander_evolves_at_zero_hp(pool):
    state, active, other = start_combat(pool)  # Atk 2 vs commander
    other["hp"] = 1
    hand_size, resources = len(other["hand"]), other["resourceField"]
    run_to_damage(state, pool)
    assert other["commander"]["stage"] == 1
    # Evol. 1's HP cell is unset in Studio: max HP falls back to Base's 10,
    # and the excess damage was dropped
    assert other["hp"] == 10 and other["maxHp"] == 10
    assert len(other["hand"]) == hand_size + 1
    assert other["resourceField"] == resources + 1
    assert state["phase"] == "combat"  # the combat finishes normally


def test_commander_with_no_evolutions_left_loses(pool):
    state, active, other = start_combat(pool)
    other["commander"]["stage"] = 1  # Keshi's last stage
    other["hp"] = 2
    run_to_damage(state, pool)
    assert state["phase"] == "over"
    assert state["players"][state["winner"]] is active
    assert "combat" not in state
    assert state["log"][-1]["msg"].endswith("wins the game")


def test_evolution_draw_from_an_empty_deck_loses(pool):
    state, active, other = start_combat(pool)
    other["hp"], other["deck"] = 1, []
    run_to_damage(state, pool)
    assert state["phase"] == "over"
    assert state["players"][state["winner"]] is active


# -- Keyword parsing (models.Card.keyword_value) -------------------------------


def test_keyword_values_parse_from_rules_text(pool):
    assert pool["Keshi Savageclaw (Base)"].keyword_value("Conjure") == 1
    assert pool["Piercing Unit"].keyword_value("Piercing") == 2
    assert pool["Armored Unit"].keyword_value("Armor") == 2
    assert pool["Haste Unit"].keyword_value("Haste") == 1
    assert pool["Common Unit"].keyword_value("Haste") is None
    double = Card(id="x", card_type="Unit", faction="Wolven", rules_text="Conjure (💠💠)")
    assert double.keyword_value("Conjure") == 2


# -- POST /game/{id} ----------------------------------------------------------


@pytest.fixture
def fake_db(monkeypatch, pool) -> FakeDb:
    fake = FakeDb()
    monkeypatch.setattr(main, "db", fake)
    monkeypatch.setattr(main, "load_cards", lambda: pool)
    return fake


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_game_attack_persists_the_combat(client, fake_db):
    game = started_game(client, fake_db)
    for player in (ALICE, BOB):
        game_post(client, game["id"], "mulligan", player, [])
    # plant an attacker and skip past round 1 in the live stored state
    stored = next(d for d in fake_db.games.docs if d["id"] == game["id"])
    state = stored["state"]
    state["round"] = 2
    active = state["players"][state["activePlayer"]]
    other = state["players"][1 - state["activePlayer"]]
    active["battleground"] = [unit("Common Unit", "a0")]
    resp = game_post(
        client, game["id"], "attack", active["user"],
        {"attacker": "a0", "target": "commander"},
    )
    assert resp.status_code == 200
    assert resp.json()["state"]["phase"] == "combat"
    assert game_post(client, game["id"], "pass", active["user"]).status_code == 200
    assert game_post(client, game["id"], "pass", other["user"]).status_code == 200
    stored = fake_db.games.find_one({"id": game["id"]})
    assert stored["state"]["combat"]["step"] == "defender"

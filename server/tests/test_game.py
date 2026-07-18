"""In-game action tests: energy plays / Artifact Cores (rulebook pp. 15-16),
resources and reserve casting (pp. 9-10, 12, 18) and the end-turn / upkeep
cycle (p. 14).

Pure action tests run over the conftest card pool (Keshi Savageclaw (Base):
Core Energy 6, conversion rate 3:1); the endpoint tests drive POST /game/{id}
through the same fake database as the other game tests.
"""

import pytest
from fastapi.testclient import TestClient

from .. import main
from ..game import cast_card, cast_reserve, convert_energy, end_turn, play_energy, rest_energy
from ..game_setup import create_game, mulligan
from ..main import app
from .test_game_setup import by_username, game_post, seat, started_game
from .test_lobby import ALICE, BOB, FakeDb


def main_phase_state(pool) -> tuple[dict, dict]:
    """A game past both mulligans, returning (state, active player)."""
    state = create_game([seat(ALICE), seat(BOB)], pool)
    for player in list(state["players"]):
        mulligan(state, player, [])
    return state, state["players"][state["activePlayer"]]


def hand_card(player: dict, card_id: str) -> dict:
    """Plant a known card in the player's hand (opening hands are random)."""
    card = {"id": card_id, "uid": f"planted-{len(player['hand'])}"}
    player["hand"].append(card)
    return card


def energy(card_id="Common Spell", uid="e0", resting=False, face_up=False) -> dict:
    return {"id": card_id, "uid": uid, "faceUp": face_up, "resting": resting}


def test_play_energy_face_down(pool):
    state, active = main_phase_state(pool)
    card = hand_card(active, "Common Unit")
    hand_size = len(active["hand"])
    assert play_energy(state, active, {"uid": card["uid"]}, pool) is state
    assert len(active["hand"]) == hand_size - 1
    assert active["energyField"] == [
        {"id": "Common Unit", "uid": card["uid"], "faceUp": False, "resting": False}
    ]
    assert active["energyPlays"] == 1
    # a face-down card is hidden information: the log never names it
    assert "Common Unit" not in state["log"][-1]["msg"]


def test_play_energy_defaults_the_counter_for_older_games(pool):
    state, active = main_phase_state(pool)
    del active["energyPlays"]  # games started before the field existed
    card = hand_card(active, "Energy Core")
    assert "error" not in play_energy(state, active, {"uid": card["uid"], "faceUp": True}, pool)
    assert active["energyPlays"] == 1


def test_first_turn_allows_a_single_energy(pool):
    state, active = main_phase_state(pool)
    play_energy(state, active, {"uid": hand_card(active, "Common Unit")["uid"]}, pool)
    result = play_energy(state, active, {"uid": hand_card(active, "Common Spell")["uid"]}, pool)
    assert "error" in result


def test_later_turns_allow_two_energy(pool):
    state, active = main_phase_state(pool)
    state["round"] = 2
    for card_id in ("Common Unit", "Common Spell"):
        card = hand_card(active, card_id)
        assert "error" not in play_energy(state, active, {"uid": card["uid"]}, pool)
    third = hand_card(active, "Energy Core")
    assert "error" in play_energy(state, active, {"uid": third["uid"]}, pool)


def test_face_up_requires_an_artifact_core(pool):
    state, active = main_phase_state(pool)
    unit = hand_card(active, "Common Unit")
    assert "error" in play_energy(state, active, {"uid": unit["uid"], "faceUp": True}, pool)
    core = hand_card(active, "Energy Core")
    play_energy(state, active, {"uid": core["uid"], "faceUp": True}, pool)
    assert active["energyField"][-1]["faceUp"] is True
    # a face-up core is public: the log names it
    assert "Energy Core" in state["log"][-1]["msg"]


def test_core_energy_caps_the_field(pool):
    state, active = main_phase_state(pool)
    state["round"] = 2
    # Keshi Savageclaw (Base) has Core Energy 6
    active["energyField"] = [energy(uid=f"e{i}") for i in range(6)]
    card = hand_card(active, "Common Unit")
    assert "error" in play_energy(state, active, {"uid": card["uid"]}, pool)
    # ...but a face-up core may swap in past the cap
    core = hand_card(active, "Energy Core")
    result = play_energy(state, active, {"uid": core["uid"], "faceUp": True, "swap": "e0"}, pool)
    assert "error" not in result
    assert len(active["energyField"]) == 6
    assert {"id": "Common Spell", "uid": "e0"} in active["hand"]


def test_swap_inherits_the_outgoing_rest(pool):
    state, active = main_phase_state(pool)
    state["round"] = 2
    active["energyField"] = [energy(uid="ready"), energy(uid="rested", resting=True)]
    core = hand_card(active, "Energy Core")
    play_energy(state, active, {"uid": core["uid"], "faceUp": True, "swap": "rested"}, pool)
    assert active["energyField"][-1]["resting"] is True
    core = hand_card(active, "Energy Core")
    play_energy(state, active, {"uid": core["uid"], "faceUp": True, "swap": "ready"}, pool)
    assert active["energyField"][-1]["resting"] is False


def test_play_energy_guards(pool):
    state, active = main_phase_state(pool)
    other = state["players"][1 - state["activePlayer"]]
    card = hand_card(other, "Common Unit")
    assert "error" in play_energy(state, other, {"uid": card["uid"]}, pool)
    assert "error" in play_energy(state, active, {"uid": "not-in-hand"}, pool)
    core = hand_card(active, "Energy Core")
    # swapping is a face-up-core-only move, and the target must be energy
    assert "error" in play_energy(state, active, {"uid": core["uid"], "swap": "e0"}, pool)
    assert "error" in play_energy(
        state, active, {"uid": core["uid"], "faceUp": True, "swap": "nope"}, pool
    )
    state["phase"] = "combat"
    assert "error" in play_energy(state, active, {"uid": core["uid"], "faceUp": True}, pool)


# -- Resting energy to pay costs (rulebook pp. 12, 15, 17) ---------------------


def test_rest_energy_rests_the_chosen_cards(pool):
    state, active = main_phase_state(pool)
    active["energyField"] = [energy(uid="e0"), energy(uid="e1"), energy(uid="e2")]
    assert rest_energy(state, active, ["e0", "e2"], pool) is state
    assert [c["resting"] for c in active["energyField"]] == [True, False, True]
    assert state["log"][-1]["msg"] == "rests 2 energy cards"


def test_rest_energy_is_allowed_on_the_opponents_turn(pool):
    # paying for an ability cast in response happens off-turn
    state, _ = main_phase_state(pool)
    other = state["players"][1 - state["activePlayer"]]
    other["energyField"] = [energy(uid="e0")]
    assert "error" not in rest_energy(state, other, ["e0"], pool)
    assert other["energyField"][0]["resting"] is True


def test_rest_energy_rejects_already_resting_cards(pool):
    state, active = main_phase_state(pool)
    active["energyField"] = [energy(uid="ready"), energy(uid="rested", resting=True)]
    assert "error" in rest_energy(state, active, ["ready", "rested"], pool)
    # a rejected action never partially applies
    assert active["energyField"][0]["resting"] is False


def test_rest_energy_guards(pool):
    state, active = main_phase_state(pool)
    active["energyField"] = [energy(uid="e0")]
    assert "error" in rest_energy(state, active, [], pool)
    assert "error" in rest_energy(state, active, None, pool)
    assert "error" in rest_energy(state, active, ["e0", "e0"], pool)
    assert "error" in rest_energy(state, active, ["not-in-field"], pool)
    state["phase"] = "mulligan"
    assert "error" in rest_energy(state, active, ["e0"], pool)


# -- Casting units and spells (rulebook pp. 17-18) -----------------------------


def test_cast_unit_rests_energy_and_enters_with_sickness(pool):
    state, active = main_phase_state(pool)
    active["energyField"] = [energy(uid=f"e{i}") for i in range(3)]
    card = hand_card(active, "Common Unit")  # cost 2
    assert cast_card(state, active, {"uid": card["uid"], "energy": ["e0", "e1"]}, pool) is state
    assert active["battleground"] == [
        {"id": "Common Unit", "uid": card["uid"], "resting": False, "enteredThisRound": True}
    ]
    assert card["uid"] not in [c["uid"] for c in active["hand"]]
    assert [c["resting"] for c in active["energyField"]] == [True, True, False]
    assert state["log"][-1]["msg"] == "casts Common Unit, resting 2 energy"


def test_cast_spell_resolves_to_the_discard_pile(pool):
    state, active = main_phase_state(pool)
    active["energyField"] = [energy(uid="e0")]
    card = hand_card(active, "Common Spell")  # cost 1
    cast_card(state, active, {"uid": card["uid"], "energy": ["e0"]}, pool)
    assert active["discard"] == [{"id": "Common Spell", "uid": card["uid"]}]
    assert active["battleground"] == []
    assert active["energyField"][0]["resting"] is True


def test_cast_a_free_card_without_energy(pool):
    state, active = main_phase_state(pool)
    card = hand_card(active, "Uncommon Unit")  # cost 0
    assert "error" not in cast_card(state, active, {"uid": card["uid"]}, pool)
    assert state["log"][-1]["msg"] == "casts Uncommon Unit"


def test_cast_requires_exact_payment(pool):
    state, active = main_phase_state(pool)
    active["energyField"] = [energy(uid=f"e{i}") for i in range(3)]
    card = hand_card(active, "Common Unit")  # cost 2
    for payment in ([], ["e0"], ["e0", "e1", "e2"]):
        assert "error" in cast_card(state, active, {"uid": card["uid"], "energy": payment}, pool)
    # a rejected cast never partially applies
    assert not any(c["resting"] for c in active["energyField"])
    assert card["uid"] in [c["uid"] for c in active["hand"]]


def test_cast_rejects_spent_or_missing_energy(pool):
    state, active = main_phase_state(pool)
    active["energyField"] = [energy(uid="ready"), energy(uid="rested", resting=True)]
    card = hand_card(active, "Common Unit")
    for payment in (["ready", "rested"], ["ready", "nope"], ["ready", "ready"]):
        assert "error" in cast_card(state, active, {"uid": card["uid"], "energy": payment}, pool)
    assert active["energyField"][0]["resting"] is False


def test_battleground_capacity_caps_units_but_not_spells(pool):
    state, active = main_phase_state(pool)
    active["energyField"] = [energy(uid=f"e{i}") for i in range(3)]
    active["battleground"] = [
        {"id": "Common Unit", "uid": f"u{i}", "resting": False} for i in range(5)
    ]
    unit = hand_card(active, "Common Unit")
    assert "error" in cast_card(state, active, {"uid": unit["uid"], "energy": ["e0", "e1"]}, pool)
    spell = hand_card(active, "Common Spell")
    assert "error" not in cast_card(state, active, {"uid": spell["uid"], "energy": ["e0"]}, pool)


def test_cast_guards(pool):
    state, active = main_phase_state(pool)
    other = state["players"][1 - state["activePlayer"]]
    theirs = hand_card(other, "Uncommon Unit")
    assert "error" in cast_card(state, other, {"uid": theirs["uid"]}, pool)
    assert "error" in cast_card(state, active, {"uid": "not-in-hand"}, pool)
    # Cores are placed as energy, abilities are their own action, and a card
    # whose cost cell is still unset in Studio can't be priced
    for card_id in ("Energy Core", "Keshi Ability", "Rare Unit"):
        card = hand_card(active, card_id)
        assert "error" in cast_card(state, active, {"uid": card["uid"]}, pool)
    state["phase"] = "mulligan"
    card = hand_card(active, "Uncommon Unit")
    assert "error" in cast_card(state, active, {"uid": card["uid"]}, pool)


# -- Converting energy into resources (rulebook p. 12) -------------------------


def test_convert_energy_generates_a_resource(pool):
    state, active = main_phase_state(pool)
    active["energyField"] = [energy(uid=f"e{i}") for i in range(4)]
    # Keshi Savageclaw (Base) converts at 3:1
    assert convert_energy(state, active, ["e0", "e1", "e2"], pool) is state
    assert [c["resting"] for c in active["energyField"]] == [True, True, True, False]
    assert active["resourceDeck"] == 3 and active["resourceField"] == 1
    assert state["log"][-1]["msg"] == "converts 3 energy into 1 Rage"


def test_convert_is_allowed_on_the_opponents_turn(pool):
    # "You can do this at any time, even during your upkeep."
    state, _ = main_phase_state(pool)
    other = state["players"][1 - state["activePlayer"]]
    other["energyField"] = [energy(uid=f"e{i}") for i in range(3)]
    assert "error" not in convert_energy(state, other, ["e0", "e1", "e2"], pool)
    assert other["resourceField"] == 1


def test_convert_requires_exactly_the_rate(pool):
    state, active = main_phase_state(pool)
    active["energyField"] = [energy(uid=f"e{i}") for i in range(4)]
    for payment in ([], ["e0", "e1"], ["e0", "e1", "e2", "e3"]):
        assert "error" in convert_energy(state, active, payment, pool)
    # a rejected conversion never partially applies
    assert not any(c["resting"] for c in active["energyField"])
    assert active["resourceField"] == 0


def test_convert_rejects_an_empty_resource_deck(pool):
    state, active = main_phase_state(pool)
    active["energyField"] = [energy(uid=f"e{i}") for i in range(3)]
    active["resourceDeck"], active["resourceField"] = 0, 4
    assert "error" in convert_energy(state, active, ["e0", "e1", "e2"], pool)
    assert not any(c["resting"] for c in active["energyField"])


def test_convert_rate_falls_back_through_stages(pool):
    # Keshi Evol. 1's conversion cell is unset in Studio: Base's 3:1 applies
    state, active = main_phase_state(pool)
    active["commander"]["stage"] = 1
    active["energyField"] = [energy(uid=f"e{i}") for i in range(3)]
    assert "error" not in convert_energy(state, active, ["e0", "e1", "e2"], pool)


def test_convert_guards(pool):
    state, active = main_phase_state(pool)
    active["energyField"] = [energy(uid="e0"), energy(uid="e1"), energy(uid="rested", resting=True)]
    assert "error" in convert_energy(state, active, ["e0", "e1", "rested"], pool)
    assert "error" in convert_energy(state, active, ["e0", "e1", "nope"], pool)
    state["phase"] = "mulligan"
    assert "error" in convert_energy(state, active, ["e0", "e1"], pool)


# -- Casting reserve cards (rulebook pp. 9-10, 18) ------------------------------


def reserve_uid(player: dict, card_id: str) -> str:
    return next(c["uid"] for c in player["reserve"] if c["id"] == card_id)


def reserve_ready(pool) -> tuple[dict, dict]:
    """A game in round 2 where the active player can afford reserve casts."""
    state, active = main_phase_state(pool)
    state["round"] = 2
    active["resourceDeck"], active["resourceField"] = 2, 2
    return state, active


def test_cast_reserve_weapon_spends_resources(pool):
    state, active = reserve_ready(pool)
    uid = reserve_uid(active, "Weapon One")  # cost 1
    assert cast_reserve(state, active, {"uid": uid}, pool) is state
    assert active["equipment"] == [
        {"id": "Weapon One", "uid": uid, "slot": "Weapon", "resting": False}
    ]
    assert uid not in [c["uid"] for c in active["reserve"]]
    # spent resources return to the resource deck
    assert active["resourceField"] == 1 and active["resourceDeck"] == 3
    assert active["reserveCasts"] == 1
    assert state["log"][-1]["msg"] == "casts Weapon One from their reserve, spending 1 Rage"


def test_cast_reserve_replaces_the_same_equipment_slot(pool):
    state, active = reserve_ready(pool)
    active["equipment"] = [
        {"id": "Weapon One", "uid": "w1", "slot": "Weapon", "resting": False},
        {"id": "Armor One", "uid": "a1", "slot": "Armor", "resting": False},
    ]
    uid = reserve_uid(active, "Weapon Two")  # cost 2
    cast_reserve(state, active, {"uid": uid}, pool)
    # the old weapon is Removed; the armor is untouched
    assert [c["uid"] for c in active["equipment"]] == ["a1", uid]
    assert active["removed"] == [{"id": "Weapon One", "uid": "w1"}]
    assert state["log"][-1]["msg"].endswith("removing Weapon One from the game")


def test_cast_reserve_battlefield_replaces_the_battlefield(pool):
    state, active = reserve_ready(pool)
    active["battlefield"] = {"id": "Battlefield Two", "uid": "b2", "resting": False}
    uid = reserve_uid(active, "Battlefield One")
    cast_reserve(state, active, {"uid": uid}, pool)
    assert active["battlefield"]["uid"] == uid
    assert active["removed"] == [{"id": "Battlefield Two", "uid": "b2"}]


def test_cast_reserve_feat_resolves_then_is_removed(pool):
    state, active = reserve_ready(pool)
    uid = reserve_uid(active, "Feat One")  # cost 0
    cast_reserve(state, active, {"uid": uid}, pool)
    assert active["removed"] == [{"id": "Feat One", "uid": uid}]
    assert active["equipment"] == [] and active["battlefield"] is None
    assert state["log"][-1]["msg"] == "casts Feat One from their reserve"


def test_cast_reserve_once_per_round(pool):
    state, active = reserve_ready(pool)
    cast_reserve(state, active, {"uid": reserve_uid(active, "Weapon One")}, pool)
    result = cast_reserve(state, active, {"uid": reserve_uid(active, "Armor One")}, pool)
    assert "error" in result
    # ...until the counter resets in the player's upkeep
    other = state["players"][1 - state["activePlayer"]]
    end_turn(state, active, None, pool)
    end_turn(state, other, None, pool)
    assert active["reserveCasts"] == 0
    assert "error" not in cast_reserve(state, active, {"uid": reserve_uid(active, "Armor One")}, pool)


def test_cast_reserve_needs_enough_resources(pool):
    state, active = reserve_ready(pool)
    active["resourceField"] = 1
    result = cast_reserve(state, active, {"uid": reserve_uid(active, "Weapon Two")}, pool)  # cost 2
    assert "error" in result
    # a rejected cast never partially applies
    assert active["resourceField"] == 1 and active["reserveCasts"] == 0
    assert "Weapon Two" in [c["id"] for c in active["reserve"]]


def test_cast_reserve_locked_until_round_two(pool):
    state, active = main_phase_state(pool)
    active["resourceField"] = 2
    assert "error" in cast_reserve(state, active, {"uid": reserve_uid(active, "Weapon One")}, pool)


def test_cast_reserve_guards(pool):
    state, active = reserve_ready(pool)
    other = state["players"][1 - state["activePlayer"]]
    other["resourceField"] = 2
    theirs = reserve_uid(other, "Weapon One")
    assert "error" in cast_reserve(state, other, {"uid": theirs}, pool)
    assert "error" in cast_reserve(state, active, {"uid": "not-in-reserve"}, pool)
    # a card whose cost cell is still unset in Studio can't be priced
    assert "error" in cast_reserve(state, active, {"uid": reserve_uid(active, "Armor Two")}, pool)
    state["phase"] = "mulligan"
    assert "error" in cast_reserve(state, active, {"uid": reserve_uid(active, "Weapon One")}, pool)


def test_upkeep_clears_summoning_sickness(pool):
    state, active = main_phase_state(pool)
    other = state["players"][1 - state["activePlayer"]]
    other["battleground"] = [
        {"id": "Common Unit", "uid": "u0", "resting": False, "enteredThisRound": True}
    ]
    end_turn(state, active, None, pool)
    assert other["battleground"][0]["enteredThisRound"] is False


# -- End turn / upkeep (rulebook p. 14) ----------------------------------------


def test_end_turn_passes_to_the_opponent_who_draws(pool):
    state, active = main_phase_state(pool)
    other = state["players"][1 - state["activePlayer"]]
    hand_size = len(other["hand"])
    assert end_turn(state, active, None, pool) is state
    assert state["players"][state["activePlayer"]] is other
    assert state["phase"] == "main"
    assert len(other["hand"]) == hand_size + 2


def test_upkeep_readies_cards_and_resets_the_energy_counter(pool):
    state, active = main_phase_state(pool)
    other = state["players"][1 - state["activePlayer"]]
    other["energyPlays"] = 2
    other["energyField"] = [energy(uid="e0", resting=True), energy(uid="e1")]
    other["battleground"] = [{"id": "Common Unit", "uid": "u0", "resting": True}]
    other["reserve"][0]["resting"] = True
    end_turn(state, active, None, pool)
    assert other["energyPlays"] == 0
    assert not any(c["resting"] for c in other["energyField"])
    assert not other["battleground"][0]["resting"]
    assert not other["reserve"][0]["resting"]


def test_round_advances_when_the_turn_returns_to_the_first_player(pool):
    state, first = main_phase_state(pool)
    second = state["players"][1 - state["activePlayer"]]
    end_turn(state, first, None, pool)
    assert state["round"] == 1
    end_turn(state, second, None, pool)
    assert state["round"] == 2
    assert state["players"][state["activePlayer"]] is first
    # past round 1 the first player gets the full two energy plays
    for card_id in ("Common Unit", "Common Spell"):
        card = hand_card(first, card_id)
        assert "error" not in play_energy(state, first, {"uid": card["uid"]}, pool)


def test_failing_the_turn_draw_loses_the_game(pool):
    state, active = main_phase_state(pool)
    other = state["players"][1 - state["activePlayer"]]
    other["deck"] = other["deck"][:1]
    end_turn(state, active, None, pool)
    assert state["phase"] == "over"
    assert state["players"][state["winner"]] is active
    assert state["log"][-1]["msg"].endswith("wins the game")
    # the game is over: no further turns can be taken
    assert "error" in end_turn(state, other, None, pool)


def test_end_turn_guards(pool):
    state, active = main_phase_state(pool)
    other = state["players"][1 - state["activePlayer"]]
    assert "error" in end_turn(state, other, None, pool)
    state["phase"] = "mulligan"
    assert "error" in end_turn(state, active, None, pool)


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


def test_game_energy_persists_and_returns_the_game(client, fake_db):
    game = started_game(client, fake_db)
    for player in (ALICE, BOB):
        game_post(client, game["id"], "mulligan", player, [])
    state = fake_db.games.find_one({"id": game["id"]})["state"]
    active = state["players"][state["activePlayer"]]
    uid = active["hand"][0]["uid"]
    resp = game_post(client, game["id"], "energy", active["user"], {"uid": uid})
    assert resp.status_code == 200
    played = by_username(resp.json()["state"], active["user"]["username"])
    assert played["energyField"][0]["uid"] == uid
    assert played["energyPlays"] == 1
    stored = fake_db.games.find_one({"id": game["id"]})
    assert by_username(stored["state"], active["user"]["username"])["energyPlays"] == 1


def test_game_rest_persists_until_upkeep(client, fake_db):
    game = started_game(client, fake_db)
    for player in (ALICE, BOB):
        game_post(client, game["id"], "mulligan", player, [])
    state = fake_db.games.find_one({"id": game["id"]})["state"]
    active = state["players"][state["activePlayer"]]
    uid = active["hand"][0]["uid"]
    game_post(client, game["id"], "energy", active["user"], {"uid": uid})
    resp = game_post(client, game["id"], "rest", active["user"], [uid])
    assert resp.status_code == 200
    rested = by_username(resp.json()["state"], active["user"]["username"])
    assert rested["energyField"][0]["resting"] is True
    # a repeat rest of the same card is rejected...
    assert game_post(client, game["id"], "rest", active["user"], [uid]).status_code == 422
    # ...until the card readies again in the player's next upkeep
    other = fake_db.games.find_one({"id": game["id"]})["state"]["players"][
        1 - state["activePlayer"]
    ]
    game_post(client, game["id"], "end", active["user"])
    resp = game_post(client, game["id"], "end", other["user"])
    readied = by_username(resp.json()["state"], active["user"]["username"])
    assert readied["energyField"][0]["resting"] is False


def test_game_cast_persists_the_unit(client, fake_db):
    game = started_game(client, fake_db)
    for player in (ALICE, BOB):
        game_post(client, game["id"], "mulligan", player, [])
    # plant a known hand card and ready energy in the live stored state
    stored = next(d for d in fake_db.games.docs if d["id"] == game["id"])
    state = stored["state"]
    active = state["players"][state["activePlayer"]]
    active["hand"].append({"id": "Common Unit", "uid": "planted"})
    active["energyField"] = [energy(uid="e0"), energy(uid="e1")]
    resp = game_post(
        client, game["id"], "cast", active["user"],
        {"uid": "planted", "energy": ["e0", "e1"]},
    )
    assert resp.status_code == 200
    caster = by_username(resp.json()["state"], active["user"]["username"])
    assert caster["battleground"][0]["uid"] == "planted"
    assert all(c["resting"] for c in caster["energyField"])
    stored = fake_db.games.find_one({"id": game["id"]})
    assert by_username(stored["state"], active["user"]["username"])["battleground"]


def test_game_end_turn_persists_the_pass(client, fake_db):
    game = started_game(client, fake_db)
    for player in (ALICE, BOB):
        game_post(client, game["id"], "mulligan", player, [])
    state = fake_db.games.find_one({"id": game["id"]})["state"]
    active = state["players"][state["activePlayer"]]
    resp = game_post(client, game["id"], "end", active["user"])
    assert resp.status_code == 200
    assert resp.json()["state"]["activePlayer"] == 1 - state["activePlayer"]
    stored = fake_db.games.find_one({"id": game["id"]})
    assert stored["state"]["activePlayer"] == 1 - state["activePlayer"]

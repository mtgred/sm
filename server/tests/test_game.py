"""Energy-play / Artifact Core action tests (rulebook pp. 15-16).

Pure `play_energy` tests run over the conftest card pool (Keshi Savageclaw
(Base): Core Energy 6); the endpoint test drives POST /game/{id} through the
same fake database as the other game tests.
"""

import pytest
from fastapi.testclient import TestClient

from .. import main
from ..game import play_energy
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

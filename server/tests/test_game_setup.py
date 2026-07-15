"""Game setup and mulligan tests.

The setup functions are pure over the conftest card pool; the endpoint tests
drive POST /game/{id} through the same fake database as the lobby tests.
"""

import pytest
from fastapi.testclient import TestClient

from .. import main
from ..game_setup import create_game, mulligan
from ..main import app
from .conftest import legal_deck
from .test_lobby import ALICE, BOB, FakeDb, post, start_ready_game


def seat(user: dict, **overrides) -> dict:
    return {"user": user, "deck": legal_deck(**overrides).model_dump()}


def two_player_state(pool) -> dict:
    return create_game([seat(ALICE), seat(BOB)], pool)


def by_username(state: dict, username: str) -> dict:
    return next(p for p in state["players"] if p["user"]["username"] == username)


def test_create_game_builds_setup_state(pool):
    state = two_player_state(pool)
    assert state["round"] == 1
    assert state["phase"] == "mulligan"
    assert state["firstPlayer"] in (0, 1)
    assert state["activePlayer"] is None
    assert {p["user"]["username"] for p in state["players"]} == {"alice", "bob"}

    for player in state["players"]:
        # 50-card main deck, opening hand of 5 drawn from it
        assert len(player["hand"]) == 5
        assert len(player["deck"]) == 45
        uids = [c["uid"] for c in player["deck"] + player["hand"]]
        assert len(set(uids)) == 50
        # Keshi Savageclaw (Base): hp 10, resource_count 4, Wolven -> Rage
        assert player["hp"] == player["maxHp"] == 10
        assert player["resource"] == "Rage"
        assert player["resourceDeck"] == 4 and player["resourceField"] == 0
        assert player["commander"] == {
            "stages": ["Keshi Savageclaw (Base)", "Keshi Savageclaw (Evol. 1)"],
            "stage": 0,
        }
        assert len(player["reserve"]) == 8
        assert player["battleground"] == [] and player["energyField"] == []
        assert not player["mulliganed"]


def test_create_game_requires_two_players(pool):
    with pytest.raises(ValueError):
        create_game([seat(ALICE)], pool)


def test_create_game_rejects_non_base_commander(pool):
    seats = [seat(ALICE, commander_id="Keshi Savageclaw (Evol. 1)"), seat(BOB)]
    with pytest.raises(ValueError, match="commander"):
        create_game(seats, pool)


def test_mulligan_keep_leaves_hand_untouched(pool):
    state = two_player_state(pool)
    alice = by_username(state, "alice")
    hand = [c["uid"] for c in alice["hand"]]
    assert mulligan(state, alice, []) is state
    assert alice["mulliganed"]
    assert [c["uid"] for c in alice["hand"]] == hand
    assert state["phase"] == "mulligan"  # bob hasn't resolved yet


def test_mulligan_bottoms_and_redraws(pool):
    state = two_player_state(pool)
    alice = by_username(state, "alice")
    returned = [c["uid"] for c in alice["hand"][:2]]
    mulligan(state, alice, returned)
    hand_uids = {c["uid"] for c in alice["hand"]}
    assert len(alice["hand"]) == 5 and len(alice["deck"]) == 45
    assert not hand_uids & set(returned)
    assert set(returned) <= {c["uid"] for c in alice["deck"]}


def test_mulligan_guards(pool):
    state = two_player_state(pool)
    alice = by_username(state, "alice")
    bob = by_username(state, "bob")
    assert "error" in mulligan(state, alice, ["not-a-hand-uid"])
    mulligan(state, alice, [])
    assert "error" in mulligan(state, alice, [])
    mulligan(state, bob, [])
    assert "error" in mulligan(state, alice, [])  # phase is over


def test_both_mulligans_begin_the_first_turn(pool):
    state = two_player_state(pool)
    for player in list(state["players"]):
        mulligan(state, player, [])
    assert state["phase"] == "main"
    assert state["activePlayer"] == state["firstPlayer"]
    first = state["players"][state["firstPlayer"]]
    other = state["players"][1 - state["firstPlayer"]]
    # the first player has taken their draw phase (2 cards)
    assert len(first["hand"]) == 7 and len(first["deck"]) == 43
    assert len(other["hand"]) == 5


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


def started_game(client, fake_db) -> dict:
    game = start_ready_game(client, fake_db)
    assert post(client, "start", ALICE, id=game["id"]).status_code == 200
    return game


def game_post(client, id: str, action: str, player: dict, data=None):
    return client.post(f"/game/{id}", json={"action": action, "player": player, "data": data})


def test_game_mulligan_persists_and_returns_the_game(client, fake_db):
    game = started_game(client, fake_db)
    resp = game_post(client, game["id"], "mulligan", ALICE, [])
    assert resp.status_code == 200
    assert by_username(resp.json()["state"], "alice")["mulliganed"]
    stored = fake_db.games.find_one({"id": game["id"]})
    assert by_username(stored["state"], "alice")["mulliganed"]


def test_game_action_rejections(client, fake_db):
    game = started_game(client, fake_db)
    # only seated players may act
    eve = {"username": "eve", "hash": "e5"}
    assert game_post(client, game["id"], "mulligan", eve, []).status_code == 403
    assert game_post(client, "nope", "mulligan", ALICE, []).status_code == 404
    assert game_post(client, game["id"], "attack", ALICE).status_code == 422
    # a game action error surfaces as 422
    game_post(client, game["id"], "mulligan", ALICE, [])
    assert game_post(client, game["id"], "mulligan", ALICE, []).status_code == 422


def test_game_action_requires_a_started_game(client, fake_db):
    game = start_ready_game(client, fake_db)  # not started
    assert game_post(client, game["id"], "mulligan", ALICE, []).status_code == 422

"""Lobby endpoint tests (GET/POST /games).

The endpoints only use a narrow slice of pymongo (find/find_one with
exclude-only projections, insert_one, $set updates, delete_one), so a tiny
in-memory fake stands in for the database — no Mongo needed.
"""

import copy

import pytest
from fastapi.testclient import TestClient

from .. import main
from ..main import app


class FakeCursor(list):
    def to_list(self):
        return list(self)


class FakeCollection:
    def __init__(self):
        self.docs: list[dict] = []

    @staticmethod
    def _match(doc: dict, query: dict | None) -> bool:
        return all(doc.get(k) == v for k, v in (query or {}).items())

    @staticmethod
    def _project(doc: dict, projection: dict | None) -> dict:
        doc = copy.deepcopy(doc)
        for field, include in (projection or {}).items():
            if include == 0:
                doc.pop(field, None)
        return doc

    def find(self, query=None, projection=None):
        return FakeCursor(
            self._project(d, projection) for d in self.docs if self._match(d, query)
        )

    def find_one(self, query=None, projection=None):
        for doc in self.docs:
            if self._match(doc, query):
                return self._project(doc, projection)
        return None

    def insert_one(self, doc):
        self.docs.append(copy.deepcopy(doc))

    def update_one(self, query, update):
        for doc in self.docs:
            if self._match(doc, query):
                for key, value in update.get("$set", {}).items():
                    doc[key] = copy.deepcopy(value)
                return

    def delete_one(self, query):
        for doc in self.docs:
            if self._match(doc, query):
                self.docs.remove(doc)
                return


class FakeDb:
    def __init__(self):
        self.games = FakeCollection()
        self.decks = FakeCollection()


ALICE = {"username": "alice", "hash": "a1"}
BOB = {"username": "bob", "hash": "b2"}


def deck_doc(id: str, owner: str, casual: bool = False, is_valid: bool = True) -> dict:
    # A legal Keshi Savageclaw deck against the conftest pool, so "start"
    # can expand it into a real game state.
    return {
        "id": id,
        "owner": owner,
        "name": f"{owner}'s {id}",
        "commander_id": "Keshi Savageclaw (Base)",
        "main_deck": [
            {"card_id": "Common Unit", "count": 25},
            {"card_id": "Common Spell", "count": 19},
            {"card_id": "Energy Core", "count": 6},
        ],
        "reserve_deck": [
            "Weapon One", "Weapon Two", "Armor One", "Armor Two",
            "Battlefield One", "Battlefield Two", "Feat One", "Feat Two",
        ],
        "casual": casual,
        "is_valid": is_valid,
        "issues": [],
    }


@pytest.fixture
def fake_db(monkeypatch, pool) -> FakeDb:
    fake = FakeDb()
    monkeypatch.setattr(main, "db", fake)
    monkeypatch.setattr(main, "load_cards", lambda: pool)
    return fake


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def post(client: TestClient, action: str, player: dict, **kwargs):
    return client.post("/games", json={"action": action, "player": player, **kwargs})


def create_game(client: TestClient, player: dict = ALICE, casual: bool = False) -> dict:
    resp = post(client, "create", player, settings={"casual": casual})
    assert resp.status_code == 200
    return resp.json()[0]


def test_create_seeds_creator_without_deck(client, fake_db):
    game = create_game(client, casual=True)
    assert game["settings"] == {"casual": True}
    assert game["players"] == [
        {"username": "alice", "hash": "a1", "deck_id": None, "deck_name": None,
         "commander_id": None, "deck_valid": None}
    ]


def test_create_requires_settings(client, fake_db):
    assert post(client, "create", ALICE).status_code == 422


def test_non_create_requires_game_id(client, fake_db):
    assert post(client, "join", ALICE).status_code == 422


def test_join_adds_player(client, fake_db):
    game = create_game(client)
    resp = post(client, "join", BOB, id=game["id"])
    assert resp.status_code == 200
    assert [p["username"] for p in resp.json()[0]["players"]] == ["alice", "bob"]


def test_join_rejects_duplicates_and_full_games(client, fake_db):
    game = create_game(client)
    assert post(client, "join", ALICE, id=game["id"]).status_code == 422
    post(client, "join", BOB, id=game["id"])
    charlie = {"username": "charlie", "hash": "c3"}
    resp = post(client, "join", charlie, id=game["id"])
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Game is full"


def test_join_missing_game_is_404(client, fake_db):
    assert post(client, "join", BOB, id="nope").status_code == 404


def test_leave_removes_player_and_deletes_empty_game(client, fake_db):
    game = create_game(client)
    post(client, "join", BOB, id=game["id"])
    resp = post(client, "leave", BOB, id=game["id"])
    assert [p["username"] for p in resp.json()[0]["players"]] == ["alice"]
    resp = post(client, "leave", ALICE, id=game["id"])
    assert resp.json() == []


def test_select_deck(client, fake_db):
    fake_db.decks.insert_one(deck_doc("d1", "alice"))
    game = create_game(client)
    resp = post(client, "deck", ALICE, id=game["id"], deck_id="d1")
    assert resp.status_code == 200
    player = resp.json()[0]["players"][0]
    assert player["deck_id"] == "d1"
    assert player["deck_name"] == "alice's d1"
    assert player["commander_id"] == "Keshi Savageclaw (Base)"


def test_select_deck_rejections(client, fake_db):
    fake_db.decks.insert_one(deck_doc("bobs", "bob"))
    fake_db.decks.insert_one(deck_doc("casual", "alice", casual=True))
    game = create_game(client)
    # someone else's deck looks like a missing deck
    assert post(client, "deck", ALICE, id=game["id"], deck_id="bobs").status_code == 404
    # format mismatch: competitive game, casual deck
    assert post(client, "deck", ALICE, id=game["id"], deck_id="casual").status_code == 422
    # not seated in the game
    fake_db.decks.insert_one(deck_doc("d1", "bob"))
    assert post(client, "deck", BOB, id=game["id"], deck_id="d1").status_code == 422


def test_select_illegal_deck_is_allowed_but_flagged(client, fake_db):
    fake_db.decks.insert_one(deck_doc("invalid", "alice", is_valid=False))
    game = create_game(client)
    resp = post(client, "deck", ALICE, id=game["id"], deck_id="invalid")
    assert resp.status_code == 200
    player = resp.json()[0]["players"][0]
    assert player["deck_id"] == "invalid"
    assert player["deck_valid"] is False


def start_ready_game(client, fake_db) -> dict:
    fake_db.decks.insert_one(deck_doc("da", "alice"))
    fake_db.decks.insert_one(deck_doc("db", "bob"))
    game = create_game(client)
    post(client, "join", BOB, id=game["id"])
    post(client, "deck", ALICE, id=game["id"], deck_id="da")
    post(client, "deck", BOB, id=game["id"], deck_id="db")
    return game


def test_start_requires_full_game_with_decks(client, fake_db):
    fake_db.decks.insert_one(deck_doc("da", "alice"))
    game = create_game(client)
    assert post(client, "start", ALICE, id=game["id"]).status_code == 422
    post(client, "join", BOB, id=game["id"])
    post(client, "deck", ALICE, id=game["id"], deck_id="da")
    resp = post(client, "start", ALICE, id=game["id"])
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Every player must select a deck"


def test_start_snapshots_decks_into_state(client, fake_db):
    game = start_ready_game(client, fake_db)
    assert post(client, "start", ALICE, id=game["id"]).status_code == 200
    stored = fake_db.games.find_one({"id": game["id"]})
    assert stored["started_at"]
    state = stored["state"]
    assert state["phase"] == "mulligan"
    # seat order is randomized at setup
    assert {p["user"]["username"] for p in state["players"]} == {"alice", "bob"}
    alice = next(p for p in state["players"] if p["user"]["username"] == "alice")
    assert len(alice["hand"]) == 5 and len(alice["deck"]) == 45
    # the game list never carries the state payload
    listed = client.get("/games").json()[0]
    assert "state" not in listed
    # and a started game can't be joined or restarted
    for action, player in [("join", {"username": "eve", "hash": "e5"}), ("start", ALICE)]:
        assert post(client, action, player, id=game["id"]).status_code == 422


def test_leave_started_game_quits_it(client, fake_db):
    game = start_ready_game(client, fake_db)
    post(client, "start", ALICE, id=game["id"])

    resp = post(client, "leave", ALICE, id=game["id"])
    assert resp.status_code == 200
    assert [p["username"] for p in resp.json()[0]["players"]] == ["bob"]
    # bob is still at the table, and sees why alice's seat went quiet
    stored = fake_db.games.find_one({"id": game["id"]})
    assert {p["user"]["username"] for p in stored["state"]["players"]} == {"alice", "bob"}
    assert {"msg": "left the game", "user": ALICE} in stored["state"]["log"]

    # once the last player leaves, the game (and its state) is gone
    assert post(client, "leave", BOB, id=game["id"]).json() == []


def test_start_recheck_rejects_deleted_deck(client, fake_db):
    game = start_ready_game(client, fake_db)
    fake_db.decks.delete_one({"id": "db"})
    resp = post(client, "start", ALICE, id=game["id"])
    assert resp.status_code == 404


def test_start_allows_deck_edited_illegal(client, fake_db):
    game = start_ready_game(client, fake_db)
    fake_db.decks.update_one({"id": "db"}, {"$set": {"is_valid": False}})
    assert post(client, "start", ALICE, id=game["id"]).status_code == 200
    assert fake_db.games.find_one({"id": game["id"]})["started_at"]


def test_start_rejects_deck_whose_commander_left_the_pool(client, fake_db):
    game = start_ready_game(client, fake_db)
    fake_db.decks.update_one({"id": "db"}, {"$set": {"commander_id": "Gone (Base)"}})
    resp = post(client, "start", ALICE, id=game["id"])
    assert resp.status_code == 422
    assert "commander" in resp.json()["detail"]


def test_get_game_returns_single_game(client, fake_db):
    game = create_game(client)
    assert client.get(f"/game/{game['id']}").json()["id"] == game["id"]
    assert client.get("/game/nope").status_code == 404

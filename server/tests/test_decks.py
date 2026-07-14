"""Deck endpoint auth tests.

Fireball forwards /api/query requests with the JWT-verified username as a
query param; the server trusts that param and does no token checks itself.
"""

import pytest
from fastapi.testclient import TestClient

from .. import main
from ..main import app
from .conftest import legal_deck
from .test_lobby import FakeDb, deck_doc


@pytest.fixture
def fake_db(monkeypatch, pool) -> FakeDb:
    fake = FakeDb()
    monkeypatch.setattr(main, "db", fake)
    monkeypatch.setattr(main, "load_cards", lambda: pool)
    return fake


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_deck_endpoints_require_username(client, fake_db):
    assert client.get("/decks").status_code == 401
    assert client.post("/decks", json=legal_deck().model_dump()).status_code == 401
    assert client.put("/decks/x", json=legal_deck().model_dump()).status_code == 401
    assert client.delete("/decks/x").status_code == 401


def test_decks_are_scoped_to_the_username(client, fake_db):
    fake_db.decks.insert_one(deck_doc("mine", "alice"))
    fake_db.decks.insert_one(deck_doc("theirs", "bob"))
    listed = client.get("/decks", params={"username": "alice"}).json()
    assert [d["id"] for d in listed] == ["mine"]


def test_create_deck_owned_by_forwarded_username(client, fake_db):
    resp = client.post("/decks", params={"username": "alice"}, json=legal_deck().model_dump())
    assert resp.status_code == 200
    assert resp.json()["owner"] == "alice"
    assert resp.json()["is_valid"]


def test_cannot_touch_another_users_deck(client, fake_db):
    deck_id = client.post(
        "/decks", params={"username": "alice"}, json=legal_deck().model_dump()
    ).json()["id"]
    body = legal_deck(name="Stolen").model_dump()
    assert client.put(f"/decks/{deck_id}", params={"username": "bob"}, json=body).status_code == 403
    assert client.delete(f"/decks/{deck_id}", params={"username": "bob"}).status_code == 403
    assert client.delete(f"/decks/{deck_id}", params={"username": "alice"}).status_code == 200


def test_cards_rules_and_validate_stay_public(client, fake_db):
    assert client.get("/rules").status_code == 200
    assert client.get("/cards").status_code == 200
    resp = client.post("/decks/validate", json=legal_deck().model_dump())
    assert resp.status_code == 200
    assert resp.json() == []

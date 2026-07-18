from datetime import datetime
from typing import Literal
from uuid import uuid4
import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, model_validator
from .db import db
from .game import cast_card, cast_reserve, convert_energy, end_turn, play_energy, rest_energy
from .game_setup import create_game, log, mulligan
from .models import Card, DeckBase, ValidationIssue
from .rules import rules_manifest
from .studio import load_cards
from .validation import validate_deck

# Platform-internal server: the browser never calls it directly. Every request
# arrives through fireball (POST /api/query or the socket layer), which
# verifies the JWT and forwards the authenticated username as a query param —
# so this server does no token verification of its own and must only be
# reachable from localhost.
app = FastAPI(title="Soulmasters API")

DECK_PROJECTION = {"_id": 0}

def current_username(username: str = "") -> str:
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return username

def find_deck(id: str) -> dict:
    deck = db.decks.find_one({"id": id}, DECK_PROJECTION)
    if not deck:
        raise HTTPException(status_code=404, detail="Deck not found")
    return deck


def require_owner(deck: dict, username: str):
    if deck["owner"] != username:
        raise HTTPException(status_code=403, detail="You don't own this deck")


def build_deck_doc(body: DeckBase, owner: str, existing: dict | None = None) -> dict:
    # Cards come from fireball's Studio table, not a collection we own
    issues = validate_deck(body, load_cards())
    now = datetime.now()
    return {
        **body.model_dump(),
        "id": existing["id"] if existing else str(uuid4()),
        "owner": owner,
        "is_valid": not any(i.severity == "error" for i in issues),
        "issues": [i.model_dump() for i in issues],
        "created_at": existing["created_at"] if existing else now,
        "updated_at": now,
    }


@app.get("/rules")
async def get_rules():
    return rules_manifest()


@app.get("/cards")
async def get_cards() -> list[Card]:
    return sorted(
        load_cards().values(),
        key=lambda c: c.printings[0].card_number if c.printings else f"~{c.id}",
    )


@app.post("/decks/validate")
async def post_validate(body: DeckBase) -> list[ValidationIssue]:
    return validate_deck(body, load_cards())


@app.get("/decks")
async def get_decks(username: str = Depends(current_username)):
    return db.decks.find({"owner": username}, DECK_PROJECTION).to_list()


@app.post("/decks")
async def post_decks(body: DeckBase, username: str = Depends(current_username)):
    deck = build_deck_doc(body, owner=username)
    db.decks.insert_one({**deck})
    return deck


@app.put("/decks/{id}")
async def put_deck(id: str, body: DeckBase, username: str = Depends(current_username)):
    existing = find_deck(id)
    require_owner(existing, username)
    deck = build_deck_doc(body, owner=username, existing=existing)
    db.decks.replace_one({"id": id}, {**deck})
    return deck


@app.delete("/decks/{id}")
async def delete_deck(id: str, username: str = Depends(current_username)):
    deck = find_deck(id)
    require_owner(deck, username)
    db.decks.delete_one({"id": id})
    return {"deleted": id}


# -- Game lobby ---------------------------------------------------------------
#
# Spoken over fireball's socket layer (fireball/server/src/socketIO.ts): the
# platform verifies the JWT, injects `player` into the request body, POSTs it
# here, and broadcasts whatever game list we return to everyone in the
# `soulmasters/lobby` channel. So `player` is trusted platform identity, and
# every action responds with the full (state-less) game list.

GAME_SIZE = 2  # Soulmasters is a two-player duel

class GameSettings(BaseModel):
    casual: bool = False


class LobbyRequest(BaseModel):
    id: str = ""
    action: Literal["create", "join", "leave", "start", "deck"]
    player: dict[str, str]
    settings: GameSettings | None = None
    deck_id: str | None = None

    @model_validator(mode="after")
    def validate_fields(self):
        if self.action != "create" and not self.id:
            raise ValueError("Game ID is required")
        if self.action == "create" and self.settings is None:
            raise ValueError("Settings are required to create a game")
        if self.action == "deck" and not self.deck_id:
            raise ValueError("A deck ID is required to select a deck")
        return self


# The stored `state` is only for the running game; the lobby list never
# carries it.
GAMES_PROJECTION = {"_id": 0, "state": 0}

def list_games() -> list[dict]:
    return db.games.find({}, GAMES_PROJECTION).to_list()


def find_game(id: str) -> dict:
    game = db.games.find_one({"id": id}, {"_id": 0})
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return game


def require_not_started(game: dict):
    if game.get("started_at"):
        raise HTTPException(status_code=422, detail="Game has already started")


def lobby_player(player: dict) -> dict:
    return {
        "username": player.get("username"),
        "hash": player.get("hash"),
        "deck_id": None,
        "deck_name": None,
        "commander_id": None,
        "deck_valid": None,
    }


def leave_game(game: dict, username: str):
    """Leaving is allowed at any point, mid-game included: quitting a running
    duel abandons it rather than pausing it, so there is always a way out of a
    game. The state's seats are a start-time snapshot and stay on the board for
    whoever is still at the table (they can leave in turn); the game document
    goes away with its last player."""
    players = [p for p in game["players"] if p["username"] != username]
    if len(players) == len(game["players"]):
        return
    if not players:
        db.games.delete_one({"id": game["id"]})
        return
    update: dict = {"players": players}
    if state := game.get("state"):
        seat = next((s for s in state["players"] if s["user"]["username"] == username), None)
        log(state, "left the game", seat)
        update["state"] = state
    db.games.update_one({"id": game["id"]}, {"$set": update})


def player_deck(game: dict, player: dict) -> dict:
    """The deck a player brings to this game, re-checked at use time (it may
    have been edited or deleted since it was selected in the lobby). An illegal
    deck is allowed through — the lobby flags it and the players decide."""
    deck = db.decks.find_one({"id": player["deck_id"]}, DECK_PROJECTION)
    if not deck or deck["owner"] != player["username"]:
        raise HTTPException(status_code=404, detail="Deck not found")
    if deck["casual"] != game["settings"]["casual"]:
        detail = "casual" if game["settings"]["casual"] else "competitive"
        raise HTTPException(status_code=422, detail=f"{deck['name']} is not a {detail} deck")
    return deck


def initial_state(game: dict) -> dict:
    """Game state via game_setup.create_game, with each player's deck
    snapshotted (expanded into piles) at start, so editing a deck never
    touches a running game."""
    seats = [
        {
            "user": {"username": p["username"], "hash": p["hash"]},
            "deck": player_deck(game, p),
        }
        for p in game["players"]
    ]
    try:
        return create_game(seats, load_cards())
    except ValueError as err:
        # e.g. the deck's commander row was edited out of the Studio pool
        raise HTTPException(status_code=422, detail=str(err))


@app.get("/games")
async def get_games():
    return list_games()


@app.get("/game/{id}")
async def get_game(id: str):
    return find_game(id)


@app.post("/games")
async def post_games(req: LobbyRequest):
    match req.action:
        case "create":
            db.games.insert_one({
                "id": str(uuid4()),
                "created_at": datetime.now(),
                "players": [lobby_player(req.player)],
                "settings": req.settings.model_dump(),
            })
        case "join":
            game = find_game(req.id)
            require_not_started(game)
            if any(p["username"] == req.player["username"] for p in game["players"]):
                raise HTTPException(status_code=422, detail="You have already joined this game")
            if len(game["players"]) >= GAME_SIZE:
                raise HTTPException(status_code=422, detail="Game is full")
            players = game["players"] + [lobby_player(req.player)]
            db.games.update_one({"id": req.id}, {"$set": {"players": players}})
        case "leave":
            leave_game(find_game(req.id), req.player["username"])
        case "deck":
            game = find_game(req.id)
            require_not_started(game)
            if not any(p["username"] == req.player["username"] for p in game["players"]):
                raise HTTPException(status_code=422, detail="You are not in this game")
            deck = player_deck(game, {**req.player, "deck_id": req.deck_id})
            players = [
                {**p, "deck_id": deck["id"], "deck_name": deck["name"],
                 "commander_id": deck["commander_id"], "deck_valid": deck["is_valid"]}
                if p["username"] == req.player["username"] else p
                for p in game["players"]
            ]
            db.games.update_one({"id": req.id}, {"$set": {"players": players}})
        case "start":
            game = find_game(req.id)
            require_not_started(game)
            if len(game["players"]) < GAME_SIZE:
                raise HTTPException(status_code=422, detail=f"{GAME_SIZE} players are required")
            if any(not p.get("deck_id") for p in game["players"]):
                raise HTTPException(status_code=422, detail="Every player must select a deck")
            db.games.update_one({"id": req.id}, {
                "$set": {"state": initial_state(game), "started_at": datetime.now()},
            })
    return list_games()


# -- In-game actions ----------------------------------------------------------
#
# Same trust model as the lobby: fireball injects `player` and broadcasts the
# returned game document to everyone in the `soulmasters/game/{id}` channel.
# Actions mutate the state dict in place (uprising-style) and return either
# the state or {"error": ...}.

GAME_ACTIONS = {
    "mulligan": mulligan,
    "energy": play_energy,
    "rest": rest_energy,
    "convert": convert_energy,
    "cast": cast_card,
    "reserve": cast_reserve,
    "end": end_turn,
}


class GameRequest(BaseModel):
    action: Literal["mulligan", "energy", "rest", "convert", "cast", "reserve", "end"]
    player: dict[str, str]
    # mulligan: hand uids to put back (empty list / omitted keeps the hand)
    # energy: {"uid": hand card, "faceUp"?: bool, "swap"?: energy uid to return}
    # rest: ready energy uids to rest, paying that much 💠
    # convert: energy uids to rest (= the conversion rate), generating 1 resource
    # cast: {"uid": hand card, "energy": energy uids to rest as its cost}
    # reserve: {"uid": reserve card to cast, paid in resources}
    # end: no payload — passes the turn to the opponent (their upkeep + draw)
    data: list[str] | dict | None = None


@app.post("/game/{id}")
async def post_game(id: str, req: GameRequest):
    game = find_game(id)
    state = game.get("state")
    if not state:
        raise HTTPException(status_code=422, detail="Game has not started")
    player = next(
        (p for p in state["players"] if p["user"]["username"] == req.player.get("username")),
        None,
    )
    if not player:
        raise HTTPException(status_code=403, detail="You are not playing in this game")
    result = GAME_ACTIONS[req.action](state, player, req.data, load_cards())
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    db.games.update_one({"id": id}, {"$set": {"state": state}})
    game["state"] = state
    return game


if __name__ == "__main__":
    # Localhost only: auth is fireball's username query param, so exposing
    # this port beyond the host would let anyone act as any user.
    uvicorn.run(app, host="127.0.0.1", port=4005)

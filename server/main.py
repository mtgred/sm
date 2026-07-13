from datetime import datetime
from uuid import uuid4
import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from .auth import Session, current_user
from .db import db
from .models import Card, DeckBase, ValidationIssue
from .rules import rules_manifest
from .studio import load_cards
from .validation import validate_deck

app = FastAPI(title="Soulmasters API")

# The deckbuilder frontend is served by the fireball platform on another
# origin; auth uses bearer tokens (no cookies), so a wildcard is safe.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DECK_PROJECTION = {"_id": 0}

def find_deck(id: str) -> dict:
    deck = db.decks.find_one({"id": id}, DECK_PROJECTION)
    if not deck:
        raise HTTPException(status_code=404, detail="Deck not found")
    return deck


def require_owner(deck: dict, user: Session):
    if deck["owner"] != user.username:
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
async def get_decks(user: Session = Depends(current_user)):
    return db.decks.find({"owner": user.username}, DECK_PROJECTION).to_list()


@app.post("/decks")
async def post_decks(body: DeckBase, user: Session = Depends(current_user)):
    deck = build_deck_doc(body, owner=user.username)
    db.decks.insert_one({**deck})
    return deck


@app.put("/decks/{id}")
async def put_deck(id: str, body: DeckBase, user: Session = Depends(current_user)):
    existing = find_deck(id)
    require_owner(existing, user)
    deck = build_deck_doc(body, owner=user.username, existing=existing)
    db.decks.replace_one({"id": id}, {**deck})
    return deck


@app.delete("/decks/{id}")
async def delete_deck(id: str, user: Session = Depends(current_user)):
    deck = find_deck(id)
    require_owner(deck, user)
    db.decks.delete_one({"id": id})
    return {"deleted": id}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=4005)

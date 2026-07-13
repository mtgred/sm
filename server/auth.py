"""Verify fireball-issued JWTs so decks belong to platform users.

Fireball signs HS256 tokens with the SECRET env var (see fireball/server/src/auth.ts);
the payload is {username, roles, hash, exp}. Both servers must share SECRET.
"""

import os
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

SECRET = os.environ.get("SECRET", "dev-secret")
bearer = HTTPBearer(auto_error=False)

class Session(dict):
    @property
    def username(self) -> str:
        return self["username"]


def decode_token(token: str) -> Session:
    try:
        return Session(jwt.decode(token, SECRET, algorithms=["HS256"]))
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Session:
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return decode_token(credentials.credentials)

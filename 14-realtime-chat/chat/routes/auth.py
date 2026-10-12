"""Authentication routes: register and login.

* ``POST /api/auth/register`` creates a user and returns a fresh JWT.
* ``POST /api/auth/login`` verifies credentials and returns a JWT.

Passwords are hashed via :mod:`chat.auth`` (never stored in plaintext).
"""
from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from chat import auth
from chat.database import get_session
from chat.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    """JSON body for login / registration."""

    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=64)


def _token_payload(user: User) -> Dict[str, str]:
    """Build the ``{access_token, username}`` response for a user."""
    token = auth.create_access_token(user.id, user.username)
    return {"access_token": token, "username": user.username}


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: Credentials, db: Session = Depends(get_session)) -> Dict[str, str]:
    """Register a new user and return a JWT.

    Returns ``409`` if the username is already taken.
    """
    username = payload.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username cannot be blank")
    existing = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Username already taken")
    user = User(username=username, password_hash=auth.hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return _token_payload(user)


@router.post("/login")
def login(payload: Credentials, db: Session = Depends(get_session)) -> Dict[str, str]:
    """Verify credentials and return a JWT, or ``401`` on failure."""
    username = payload.username.strip()
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not auth.verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return _token_payload(user)
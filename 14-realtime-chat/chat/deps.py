"""FastAPI dependency factories shared by HTTP routes and the WS endpoint."""
from __future__ import annotations

from typing import Optional, Tuple

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from chat import auth
from chat.database import get_session
from chat.models import User

# ``auto_error=False`` so we can raise our own, consistent 401 messages.
_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_session),
) -> User:
    """Resolve the authenticated user from ``Authorization: Bearer <jwt>``.

    Raises ``401`` when the header is missing, the token is invalid/expired,
    or the referenced user no longer exists / is deactivated.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing bearer token",
    )
    if credentials is None:
        raise unauthorized
    payload = auth.decode_access_token(credentials.credentials)
    if payload is None:
        raise unauthorized
    user_id, _username = payload
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return user


def get_current_user_creds(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Tuple[int, str]:
    """Resolve ``(user_id, username)`` from the JWT for use in WS handlers."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    payload = auth.decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return payload


def verify_ws_token(token: Optional[str]) -> Tuple[int, str]:
    """Validate a WebSocket ``?token=...`` JWT, raising ``403`` when invalid.

    The WS route calls this eagerly so an unauthenticated client is rejected
    *before* the socket is ever accepted.
    """
    if not token:
        raise HTTPException(status_code=403, detail="Missing token")
    payload = auth.decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=403, detail="Invalid or expired token")
    user_id, username = payload
    return user_id, username
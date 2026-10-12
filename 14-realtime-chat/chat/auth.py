"""Authentication helpers: password hashing and JWT tokens.

Hashing strategy:
    * Prefer ``passlib`` with the ``bcrypt`` backend when importable.
    * Fall back to stdlib ``hashlib.scrypt`` (secure, no extra dependency).
The hash format is tagged with a prefix so a stored hash can always be re-read
robustly and the method swapped later without breaking existing users.

JWT strategy:
    * Prefer ``PyJWT`` when importable.
    * Fall back to a compact, self-contained stdlib HMAC-SHA256 JWT
      (header.payload.signature) so the app still works without the dep.

Only the JWT ``sub`` (user id), ``username``, and ``exp`` claim are used.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Dict, Optional, Tuple

# PyJWT importable?
try:
    import jwt as _jwt  # type: ignore

    _HAS_PYJWT = True
except Exception:  # pragma: no cover - depends on environment
    _jwt = None
    _HAS_PYJWT = False

# passlib + bcrypt importable?
try:
    import bcrypt as _bcrypt  # type: ignore

    _HAS_BCRYPT = True
except Exception:  # pragma: no cover - depends on environment
    _bcrypt = None
    _HAS_BCRYPT = False


# --------------------------------------------------------------------------- #
# Configuration (override via env for production)
# --------------------------------------------------------------------------- #
SECRET_KEY = os.environ.get("CHAT_SECRET_KEY", "dev-secret-change-me")
JWT_ALG = "HS256"
JWT_EXPIRES_SECONDS = int(os.environ.get("CHAT_JWT_TTL", 60 * 60 * 24))  # 1 day

SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1

# Valid UTF-8 chars for plaintext passwords (bcrypt/latin-1 safety).
PASSWORD_MAX_BYTES = 64


# --------------------------------------------------------------------------- #
# Password hashing
# --------------------------------------------------------------------------- #
def _limitable_encode(password: str) -> bytes:
    """Encode password safely; reject over-length to avoid bcrypt truncation."""
    encoded = password.encode("utf-8")
    if len(encoded) > PASSWORD_MAX_BYTES:
        raise ValueError("Password too long")
    return encoded


def hash_password(password: str) -> str:
    """Return a tagged, salted password hash string. Never stores plaintext."""
    if _HAS_BCRYPT:
        pwd = _limitable_encode(password)
        hashed = _bcrypt.hashpw(pwd, _bcrypt.gensalt())
        return f"bcrypt${hashed.decode('ascii')}"
    # stdlib scrypt fallback: salt + digest, hex-encoded.
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
    )
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time-ish verification of a password against a stored hash."""
    if not stored:
        return False
    try:
        if stored.startswith("bcrypt$"):
            if not _HAS_BCRYPT:
                return False
            pwd = _limitable_encode(password)
            hashed = stored.split("$", 1)[1].encode("ascii")
            return _bcrypt.checkpw(pwd, hashed)
        if stored.startswith("scrypt$"):
            _, salt_hex, digest_hex = stored.split("$", 2)
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(digest_hex)
            actual = hashlib.scrypt(
                password.encode("utf-8"),
                salt=salt,
                n=SCRYPT_N,
                r=SCRYPT_R,
                p=SCRYPT_P,
            )
            return hmac.compare_digest(actual, expected)
    except Exception:
        return False
    return False


# --------------------------------------------------------------------------- #
# JWT helpers
# --------------------------------------------------------------------------- #
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _create_token(payload: Dict[str, Any]) -> str:
    if _HAS_PYJWT:
        return _jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALG)
    header = {"alg": JWT_ALG, "typ": "JWT"}
    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    )
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    sig = hmac.new(SECRET_KEY.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{signing_input.decode('ascii')}.{_b64url(sig)}"


def create_access_token(user_id: int, username: str) -> str:
    """Create a signed JWT for the given user."""
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "username": username,
        "iat": now,
        "exp": now + JWT_EXPIRES_SECONDS,
    }
    return _create_token(payload)


def _decode_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode + validate a token. Returns claims dict or None on any failure."""
    if not token:
        return None
    try:
        if _HAS_PYJWT:
            return _jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALG])
        # stdlib path: header.payload.signature
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, payload_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        expected = hmac.new(
            SECRET_KEY.encode("utf-8"), signing_input, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(expected, _b64url_decode(sig_b64)):
            return None
        header = json.loads(_b64url_decode(header_b64))
        if header.get("alg") != JWT_ALG:
            return None
        payload = json.loads(_b64url_decode(payload_b64))
        exp = payload.get("exp")
        if exp is not None and int(exp) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def decode_access_token(token: str) -> Optional[Tuple[int, str]]:
    """Validate token and return ``(user_id, username)`` or ``None``."""
    payload = _decode_token(token)
    if payload is None:
        return None
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        return None
    username = payload.get("username", "")
    return user_id, username


# --------------------------------------------------------------------------- #
# Prototype quick check (removed in production).
# --------------------------------------------------------------------------- #
def _self_test() -> None:
    """Smoke-test hash + token round-trips. Not used by the app."""
    pw = "correct horse battery"
    h = hash_password(pw)
    assert verify_password(pw, h)
    assert not verify_password("wrong", h)
    tok = create_access_token(3, "alice")
    assert decode_access_token(tok) == (3, "alice")
    assert decode_access_token(tok + "x") is None
    bad = create_access_token(3, "alice")
    assert decode_access_token("x." + bad.split(".", 1)[1]) is None
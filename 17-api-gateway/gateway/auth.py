"""Authentication primitives: salted password hashing and HMAC-HS256 JWTs.

Everything here is standard-library only (no PyJWT, no bcrypt) so the gateway
runs anywhere Python runs. ``hash_password`` uses PBKDF2-HMAC-SHA256 with a
random 16-byte salt and 300k rounds; ``verify_password`` is constant-time.

JWTs are small by design (admin/session tokens only, never for API keys) and
are signed with ``settings.jwt_secret`` — a separate secret from the API-key
HMAC so the two can be rotated independently.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Dict, Optional

from gateway.config import settings

# --------------------------------------------------------------------------- #
# Password hashing (PBKDF2-HMAC-SHA256)
# --------------------------------------------------------------------------- #
_ALGO = "pbkdf2_sha256"
_SALT_BYTES = 16
_ITERATIONS = 300_000


def hash_password(password: str) -> str:
    """Return a self-describing salted hash: ``pbkdf2_sha256$it$salt$digest``."""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"{_ALGO}${_ITERATIONS}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    """Timing-safe check of a plaintext password against a stored hash."""
    try:
        algo, iters, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    if algo != _ALGO:
        return False
    try:
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        iterations = int(iters)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


# --------------------------------------------------------------------------- #
# JWT (HS256)
# --------------------------------------------------------------------------- #
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.b64decode(s)


def encode_jwt(payload: Dict[str, Any], expires_minutes: Optional[int] = None) -> str:
    """Create a signed HS256 JWT containing ``payload`` enriched with exp/iat."""
    now = int(time.time())
    body = dict(payload)
    body.setdefault("iat", now)
    body.setdefault("exp", now + (expires_minutes or settings.jwt_expire_minutes) * 60)
    header = {"alg": "HS256", "typ": "JWT"}
    h = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p = _b64url(json.dumps(body, separators=(",", ":")).encode("utf-8"))
    signing = f"{h}.{p}"
    sig = hmac.new(settings.jwt_secret.encode("utf-8"), signing.encode("utf-8"), hashlib.sha256).digest()
    s = _b64url(sig)
    return f"{signing}.{s}"


def decode_jwt(token: str) -> Dict[str, Any]:
    """Verify signature + expiry and return the JWT claims.

    Raises :class:`ValueError` for any malformed, tampered, or expired token.
    """
    try:
        h, p, s = token.split(".")
    except ValueError:
        raise ValueError("malformed jwt token")
    signing = f"{h}.{p}"
    expected = hmac.new(settings.jwt_secret.encode("utf-8"), signing.encode("utf-8"), hashlib.sha256).digest()
    provided = _unb64url_pad(s)
    if not hmac.compare_digest(provided, expected):
        raise ValueError("bad jwt signature")
    claims: Dict[str, Any] = json.loads(_unb64url_pad(p))
    exp = claims.get("exp")
    if exp is not None and int(time.time()) >= int(exp):
        raise ValueError("jwt expired")
    return claims


def _unb64url_pad(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


# --------------------------------------------------------------------------- #
# Bearer extraction helper
# --------------------------------------------------------------------------- #
def bearer_token(authorization: Optional[str]) -> Optional[str]:
    """Strip a ``Bearer <token>`` header down to the token, or None."""
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()
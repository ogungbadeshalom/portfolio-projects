"""API key generation, hashing, and verification.

Security model
--------------
* Plaintext keys look like ``sk_live_<52 hex chars>`` — a visible prefix plus
  ~256 bits of randomness (token-highway readable, collision-safe).
* Only an HMAC-SHA256 digest of the key is stored (in ``api_keys.key_hash``).
* ``verify_key(plaintext)`` recomputes the digest with the server secret and
  looks the tenant up — the plaintext is never persisted, so a DB leak does
  not reveal usable keys.
* OAuth2-style flow: you can rotate the server secret and invalidate every
  existing key by changing ``settings.secret_key``.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Optional

from sqlalchemy.orm import Session

from gateway.config import settings
from gateway.models import ApiKey

KEY_PREFIX = "sk_live_"
_HASH_ALGO = hashlib.sha256


def _digest(secret: str, plaintext: str) -> str:
    """HMAC-SHA256(secret, pepper || plaintext) hex digest.

    The ``key_hmac_pepper`` (a constant domain separator) prevents the same
    secret bytes from being re-used for API-key hashing and, say, JWT
    signing — a defense-in-depth measure against cross-protocol key reuse.
    """
    message = (settings.key_hmac_pepper + plaintext).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, _HASH_ALGO).hexdigest()


def generate_key() -> str:
    """Return a fresh plaintext API key: ``sk_live_<random>``."""
    return KEY_PREFIX + secrets.token_hex(26)


def hash_key(plaintext: str) -> str:
    """Return the HMAC-SHA256 hex digest of a plaintext key."""
    return _digest(settings.secret_key, plaintext)


def verify_key(db: Session, plaintext: str) -> Optional[ApiKey]:
    """Return the live ApiKey for ``plaintext``, or None.

    A key is rejected when:
      * no row matches the digest,
      * the key has been revoked,
      * or the key is expired.
    """
    if not isinstance(plaintext, str) or not plaintext:
        return None
    digest = hash_key(plaintext)
    row = (
        db.query(ApiKey)
        .filter(ApiKey.key_hash == digest)
        .first()
    )
    if row is None:
        return None
    if row.revoked:
        return None
    if row.expires_at is not None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        expires = (
            row.expires_at
            if row.expires_at.tzinfo is not None
            else row.expires_at.replace(tzinfo=timezone.utc)
        )
        if now > expires:
            return None
    return row
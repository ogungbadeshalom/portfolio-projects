"""Signed tokens and URL safety helpers (stdlib only: hmac, hashlib, secrets).

The unsubscribe token presented in ``GET /api/unsubscribe?token=...`` is an
HMAC-signed, URL-safe string. Signing with an app secret prevents an attacker
who learns or guesses a subscriber's random secret from forging a valid one,
and binds the token to the subscriber's email so it cannot be replayed against
another address.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from urllib.parse import urlparse

from newsletter.config import settings


def _sign(payload: str, key: bytes) -> str:
    """HMAC-SHA256 of ``payload``, URL-safe base64 encoded (no padding)."""
    digest = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _constant_time_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("ascii"), b.encode("ascii"))


def make_unsubscribe_token(email: str, secret: str, signing_key: bytes | None = None) -> str:
    """Produce ``<email>-<secret>-<sig>`` where sig authenticates both.

    ``email`` is lowercased before signing so the token is stable regardless of
    how the subscriber's address is typed in a link.
    """
    email = email.strip().lower()
    signing_key = signing_key or settings.hmac_secret.encode("utf-8")
    payload = f"{email}:{secret}"
    sig = _sign(payload, signing_key)
    return f"{email}|{secret}|{sig}"


def verify_unsubscribe_token(token: str, signing_key: bytes | None = None) -> str | None:
    """Validate a token and return the subscriber email it belongs to, or None.

    Only tokens whose signature matches the app secret are accepted, so
    tampered or fabricated tokens are rejected without ever touching the DB.
    """
    parts = token.split("|")
    if len(parts) != 3:
        return None
    email, secret, given_sig = parts
    signing_key = signing_key or settings.hmac_secret.encode("utf-8")
    payload = f"{email}:{secret}"
    expected_sig = _sign(payload, signing_key)
    if not _constant_time_equal(given_sig, expected_sig):
        return None
    return email.lower()


def make_confirm_token(email: str, secret: str) -> str:
    """Confirmation (double opt-in) token — same construction, distinct purpose.

    Kept as a separate name so the confirmation link and the unsubscribe link
    cannot be confused, even though both are HMAC-signed server-side.
    """
    return make_unsubscribe_token(email, secret)


def new_secret() -> str:
    """Cryptographically random secret for a new subscriber or outbox address."""
    return secrets.token_urlsafe(32)


# --- URL safety ---------------------------------------------------------------

_ALLOWED_CLICK_SCHEMES = {"http", "https"}


def is_safe_redirect_url(target: str) -> bool:
    """Return True only if ``target`` is safe to redirect a tracking click to.

    Guards against open-redirect abuse: requires http(s), a real netloc, and no
    embedded username/password or unusual characters. The scheme+netloc check
    rejects ``javascript:``, ``//evil.com``, ``file://`` and similar.
    """
    try:
        parsed = urlparse(target)
    except ValueError:  # malformed URL (e.g. control characters / invalid port)
        return False
    if parsed.scheme not in _ALLOWED_CLICK_SCHEMES:
        return False
    if not parsed.netloc:
        return False
    # Reject userinfo ("user:pass@host") -- commonly abused in phishing redirects.
    if parsed.username or parsed.password:
        return False
    return True
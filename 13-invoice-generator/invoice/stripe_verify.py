"""Stripe webhook signature verification.

Two implementations:

1. :func:`verify_with_sdk` — uses the official ``stripe`` SDK's
   ``WebhookSignature.verify_header`` call.  Used when the SDK is importable.
2. :func:`verify_with_hashlib` — a dependency-free implementation of the same
   standard algorithm (HMAC-SHA256 over the raw payload bytes with the
   ``t=...,v1=...`` header), including the timestamp-tolerance check.

``verify_stripe_signature`` picks the SDK when available and otherwise falls
back to the pure-stdlib path, so the webhook works even with no third-party
Stripe dependency installed.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Optional

from . import config

logger = logging.getLogger(__name__)

# Header format produced by Stripe:  t=1590029191,v1=abc...,v0=...
_V1 = "v1="
_TIME = "t="


class SignatureVerificationError(Exception):
    """Raised when a webhook signature cannot be authenticated."""


def _looks_like_sig(data: bytes) -> bool:
    """Payload chunk passed to verify is the signature portion, not event JSON."""
    return isinstance(data, bytes) and len(data) <= 4096


# ---------------------------------------------------------------------------
# Pure-stdlib implementation (works without the SDK)
# ---------------------------------------------------------------------------
def verify_with_hashlib(
    payload: bytes,
    sig_header: str,
    secret: Optional[str] = None,
    *,
    tolerance_s: Optional[int] = None,
) -> None:
    """Verify a Stripe webhook signature using only the stdlib.

    Implements the documented algorithm:

    * parse ``t=<ts>,v1=<mac>`` from the header
    * reject if the timestamp is outside ``now ± tolerance_s``
    * compute ``HMAC_SHA256(secret, payload)`` where the signed message is
      ``b"<ts>.<payload>"``
    * compare in constant time against the provided ``v1``

    :raises SignatureVerificationError: on any auth failure.
    """
    secret = secret or config.STRIPE_WEBHOOK_SECRET
    tolerance_s = tolerance_s if tolerance_s is not None else config.STRIPE_WEBHOOK_TOLERANCE_S
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes, got %r" % type(payload))

    try:
        timestamp = _parse_timestamp(sig_header)
        signature = _parse_signature(sig_header, _V1)
    except ValueError as exc:
        raise SignatureVerificationError("malformed signature header: %s" % exc)

    if timestamp is None:
        raise SignatureVerificationError("missing timestamp (t=) in signature header")

    # 1) Timestamp window.
    if tolerance_s is not None:
        now = int(time.time())
        if abs(now - timestamp) > tolerance_s:
            raise SignatureVerificationError(
                "timestamp outside tolerance window: %s vs now=%s" % (timestamp, now)
            )

    # 2) HMAC.
    expected = "".encode("utf-8")
    if not signature:
        raise SignatureVerificationError("missing v1 signature")
    signed_payload = ("%d.%s" % (timestamp, payload.decode("utf-8", "replace"))).encode("utf-8")
    mac = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, signature):
        raise SignatureVerificationError("signature does not match expected v1 sig")


def _parse_timestamp(sig_header: str) -> Optional[int]:
    for part in sig_header.split(","):
        if part.startswith(_TIME):
            try:
                return int(part[len(_TIME):])
            except ValueError:
                return None
    return None


def _parse_signature(sig_header: str, prefix: str) -> str:
    for part in sig_header.split(","):
        if part.startswith(prefix):
            return part[len(prefix):]
    return ""


# ---------------------------------------------------------------------------
# SDK implementation (preferred when ``stripe`` is installed)
# ---------------------------------------------------------------------------
def verify_with_sdk(
    payload: bytes,
    sig_header: str,
    secret: Optional[str] = None,
    *,
    tolerance_s: Optional[int] = None,
) -> None:
    """Verify using the official ``stripe`` SDK."""
    try:
        import stripe  # type: ignore
        from stripe import WebhookSignature  # type: ignore
    except Exception as exc:  # pragma: no cover - SDK absent
        raise SignatureVerificationError("stripe SDK not importable: %s" % exc)

    secret = secret or config.STRIPE_WEBHOOK_SECRET
    tolerance_s = tolerance_s if tolerance_s is not None else config.STRIPE_WEBHOOK_TOLERANCE_S
    try:
        WebhookSignature.verify_header(
            payload,
            sig_header,
            secret,
            tolerance=tolerance_s,
        )
    except Exception as exc:
        logger.warning("stripe SDK signature verification failed: %s", exc)
        raise SignatureVerificationError("invalid signature: %s" % exc)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def verify_stripe_signature(
    payload: bytes,
    sig_header: str,
    secret: Optional[str] = None,
    *,
    tolerance_s: Optional[int] = None,
) -> None:
    """Verify a Stripe webhook signature.

    Prefers the ``stripe`` SDK when importable; falls back to the pure-stdlib
    HMAC-SHA256 implementation otherwise.  Raises
    :class:`SignatureVerificationError` on any failure.

    :param payload: raw request body bytes (never decoded/re-encoded).
    :param sig_header: value of the ``Stripe-Signature`` header.
    """
    try:
        import stripe  # noqa: F401
    except Exception:
        use_sdk = False
    else:
        use_sdk = True

    if use_sdk:
        verify_with_sdk(payload, sig_header, secret, tolerance_s=tolerance_s)
    else:
        verify_with_hashlib(payload, sig_header, secret, tolerance_s=tolerance_s)


# ---------------------------------------------------------------------------
# Test / simulation utility
# ---------------------------------------------------------------------------
def sign_payload(
    payload_bytes: bytes,
    secret: str,
    timestamp: Optional[int] = None,
) -> str:
    """Build a valid ``Stripe-Signature`` header for the given payload+secret.

    Intended for the test harness and the local simulate route so that a fake
    webhook can be exercised end-to-end without talking to Stripe.
    """
    stamp = timestamp or int(time.time())
    signed = ("%d.%s" % (stamp, payload_bytes.decode("utf-8", "replace"))).encode("utf-8")
    mac = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return "t=%d,v1=%s" % (stamp, mac)
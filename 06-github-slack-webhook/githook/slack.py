"""Slack Block Kit delivery via Incoming Webhooks.

This module owns the single outbound network hop in the project: sending a
formatted Block Kit message to Slack's ``slack.com/api/chat.postMessage``-style
Incoming Webhook URL.

Design notes
------------
* **Injectability**: ``send_to_slack`` accepts a ``transport`` argument. Tests
  pass an ``httpx.MockTransport`` so nothing ever reaches the real Slack API,
  while the default is a real pool (``httpx.Client``) for production.
* **Retries**: Slack reliably uses HTTP ``429 Too Many Requests`` and (less
  often) ``5xx`` to throttle/back-off. We retry those with an exponential
  backoff whose schedule lives in ``githook.retry``.
* **Blocking discipline**: by default the *caller* decides whether to block.
  ``send_to_slack`` itself is synchronous (it owns an ``httpx.Client``);
  ``githook.webhook`` runs it on a background worker so the webhook response
  is never gated on Slack's latency.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from githook.retry import backoff_seconds

logger = logging.getLogger(__name__)

# Slack returns 429 / 5xx when it wants us to back off. Any other HTTP status
# (2xx, 3xx realm) is treated as a hard failure we should not retry blindly.
_RETRYABLE_STATUS = frozenset((429, 500, 502, 503, 504))


@dataclass
class SlackResult:
    """Outcome of a deliver-to-Slack attempt (or the whole retry cycle)."""

    success: bool
    status_code: Optional[int] = None
    attempts: int = 0

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<SlackResult success={self.success} status={self.status_code} "
            f"attempts={self.attempts}>"
        )


def build_payload(blocks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Wrap Block Kit blocks in the top-level Slack payload envelope.

    ``text`` is a plain-text fallback for notifications/clients that cannot
    render blocks (also shown when the message is collapsed).
    """
    first_text = _first_plain_text(blocks) or "Webhook notification"
    return {"blocks": blocks, "text": first_text}


def _first_plain_text(blocks: List[Dict[str, Any]], limit: int = 300) -> str:
    """Best-effort plain-text summary from the first header/section block."""
    for block in blocks:
        text = (block.get("text") or {}).get("text") if isinstance(block.get("text", {}), dict) else None
        if not text:
            continue
        # Strip markdown link syntax `<https://x|label>` down to the label.
        text = _strip_md_links(str(text))
        return text[:limit]
    return ""


def _strip_md_links(text: str) -> str:
    import re

    return re.sub(r"<[^>|]+\|([^>]+)>", r"\1", text)


def send_to_slack(
    webhook_url: str,
    blocks: List[Dict[str, Any]],
    *,
    max_retries: int = 3,
    backoff_base_seconds: float = 1.0,
    transport: Optional[httpx.BaseTransport] = None,
    timeout: float = 10.0,
) -> SlackResult:
    """Deliver ``blocks`` to ``webhook_url`` with retry + backoff.

    Takes a single delivery attempt via ``_post`` (which owns an ``httpx``
    client). On retryable statuses (429 / 5xx) or network errors we sleep for
    ``backoff_seconds(attempt, base)`` and try again, up to ``max_retries``
    total attempts.

    ``transport`` is passed straight through to ``httpx.Client`` so tests can
    substitute an ``httpx.MockTransport`` (a no-network, fully synchronous
    stand-in).
    """
    if not webhook_url:
        logger.warning("No SLACK_WEBHOOK_URL configured; treating send as skipped.")
        return SlackResult(success=False, status_code=None, attempts=1)

    payload = build_payload(blocks)
    attempt = 0
    while attempt < max_retries:
        attempt += 1
        try:
            response = _post(webhook_url, payload, transport=transport, timeout=timeout)
        except httpx.HTTPError as exc:  # network errors are transient -> retry
            logger.warning("Slack POST failed (attempt %d/%d): %s", attempt, max_retries, exc)
            if attempt >= max_retries:
                return SlackResult(success=False, status_code=None, attempts=attempt)
            _sleep_backoff(attempt, backoff_base_seconds)
            continue

        if response.status_code == 200 or 200 <= response.status_code < 300:
            return SlackResult(success=True, status_code=response.status_code, attempts=attempt)

        if response.status_code in _RETRYABLE_STATUS and attempt < max_retries:
            logger.warning(
                "Slack rate-limited (HTTP %d) attempt %d/%d; backing off.",
                response.status_code,
                attempt,
                max_retries,
            )
            _sleep_backoff(attempt, backoff_base_seconds)
            continue

        return SlackResult(success=False, status_code=response.status_code, attempts=attempt)

    return SlackResult(success=False, attempts=attempt)


def _post(
    webhook_url: str,
    payload: Dict[str, Any],
    *,
    transport: Optional[httpx.BaseTransport],
    timeout: float,
) -> httpx.Response:
    """Perform one POST of ``payload`` (JSON) to ``webhook_url``."""
    kwargs: Dict[str, Any] = {"timeout": timeout}
    if transport is not None:
        kwargs["transport"] = transport
    with httpx.Client(**kwargs) as client:
        return client.post(webhook_url, json=payload)


def _sleep_backoff(attempt: int, base: float) -> None:
    """Block the calling thread for the exponential backoff of ``attempt``."""
    import time

    delay = backoff_seconds(attempt, base)
    logger.info("Sleeping %.2fs before retry (attempt %d).", delay, attempt)
    time.sleep(delay)
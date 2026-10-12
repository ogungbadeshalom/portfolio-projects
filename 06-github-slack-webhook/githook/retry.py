"""Retry queue and delivery driver for Slack webhook sends.

Slack sends fail in production (rate limits, transient 5xx, network blips).
This module provides two layers of reliability:

* ``backoff_seconds`` -- the exponential schedule used between delivery
  attempts (shared by ``githook.slack`` and private to this package).
* ``delivery_retrier`` -- drives a full send attempt cycle: try
  ``send_to_slack``, update the event's persisted status, and (in the verbose
  mode) push failures onto the in-memory ``RetryQueue`` for a human or
  background worker to re-run later.

The ``RetryQueue`` is an ordinary in-memory FIFO de-duplicated by delivery id;
it is intentionally simple (no Redis) so the project runs anywhere, and its
interface is small enough to swap for a real queue later.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

from githook.events import EventStore

logger = logging.getLogger(__name__)

# Cap the schedule so a pathological failure storm can't trigger multi-minute
# sleeps in tests or during a demo.
_MAX_BACKOFF_SECONDS = 60.0


def backoff_seconds(attempt: int, base: float = 1.0) -> float:
    """Return the exponential backoff for ``attempt`` (1-based).

    ``backoff_seconds(1, 1.0) == 1.0``, ``backoff_seconds(2, 1.0) == 2.0``,
    ``backoff_seconds(3, 1.0) == 4.0`` — capped at 60s.
    """
    if base <= 0:
        base = 1.0
    if attempt <= 0:
        attempt = 1
    return min(base * (2 ** (attempt - 1)), _MAX_BACKOFF_SECONDS)


class RetryQueue:
    """Thread-safe in-memory FIFO of delivery ids waiting for a retry."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ids: "List[int]" = []  # delivery ids, insertion order
        self._seen: "set[int]" = set()

    def enqueue(self, delivery_id: str) -> bool:
        """Record ``delivery_id`` for a later retry.

        Returns False if the id is already queued (de-duplication).
        """
        with self._lock:
            if delivery_id in self._seen:
                return False
            self._seen.add(delivery_id)
            self._ids.append(delivery_id)
            logger.info("Enqueued delivery %r for retry.", delivery_id)
            return True

    def dequeue(self) -> Optional[str]:
        """Pop the oldest delivery id, or None if the queue is empty."""
        with self._lock:
            if not self._ids:
                return None
            first = self._ids.pop(0)
            self._seen.discard(first)
            return first

    def snapshot(self) -> List[str]:
        """Return a copy of the queued delivery ids (oldest first)."""
        with self._lock:
            return list(self._ids)

    def __len__(self) -> int:
        with self._lock:
            return len(self._ids)


def delivery_retrier(
    store: EventStore,
    send_to_slack,
    webhook_url: str,
    blocks: List[Dict[str, Any]],
    delivery_id: str,
    *,
    max_retries: int = 3,
    backoff_base: float = 1.0,
    retry_queue: Optional[RetryQueue] = None,
    transport=None,
    sync: bool = True,
) -> bool:
    """Drive a full delivery attempt and persist its outcome.

    The signature is deliberately "delegation" shaped so that ``app.py`` can
    hand us any ``send_to_slack``-compatible callable (real or mock) and any
    ``EventStore`` (SQLAlchemy or stdlib sqlite).

    Returns ``True`` if the message was accepted by Slack.
    """
    result = send_to_slack(
        webhook_url,
        blocks,
        max_retries=max_retries,
        backoff_base_seconds=backoff_base,
        transport=transport,
    )

    if result.success:
        store.mark_delivered(delivery_id)
        logger.info("Delivery %r marked delivered.", delivery_id)
        return True

    store.mark_failed(delivery_id, result.attempts)
    logger.error("Delivery %r failed after %d attempts.", delivery_id, result.attempts)
    if retry_queue is not None:
        retry_queue.enqueue(delivery_id)
    return False
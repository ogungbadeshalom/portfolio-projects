"""Example task handlers registered on the shared registry.

These make the CLI/API immediately runnable and demonstrate idempotency and
failure (for the DMQ) without writing your own functions. Import this module
once at process start (the CLI and FastAPI app both do) to register them.
"""

from __future__ import annotations

import json
import logging
import random
import time

from scheduler.registry import registry

logger = logging.getLogger(__name__)


@registry.task(name="send_email")
def send_email(to: str, subject: str = "no subject", body: str = "") -> str:
    """Pretend to send an email; always succeeds."""
    logger.info("sending email to %s: %s", to, subject)
    return f"emailed {to} ({subject})"


@registry.task(name="cleanup")
def cleanup(limit: int = 1000) -> str:
    """Pretend to purge old records."""
    logger.info("cleaned up %d records", limit)
    return f"cleaned {limit} rows"


@registry.task(name="ping", idempotency_fn=lambda payload: payload.get("key"))
def ping(node: str = "unknown") -> str:
    """A no-op heartbeat for liveliness demos."""
    return f"pong from {node}"


@registry.task(name="fail_task")
def fail_task(rate: float = 1.0) -> str:
    """Purposefully fail (for exercising the dead-letter queue)."""
    if random.random() > rate:
        return "unexpectedly succeeded"
    raise RuntimeError("intentional task failure for DLQ demo")


@registry.task(name="slow_task")
def slow_task(seconds: float = 2.0) -> str:
    """Sleep then succeed — demonstrates the worker timeout when seconds > timeout."""
    time.sleep(float(seconds))
    return f"slept {seconds}s"


@registry.task(name="add")
def add(a: float, b: float) -> float:
    """Pure compute handler used by the tests."""
    return float(a) + float(b)


def register_all() -> None:
    """Idempotent import hook (importing the module already registers)."""
    # Functions above are registered at import time.


__all__ = [
    "send_email",
    "cleanup",
    "ping",
    "fail_task",
    "slow_task",
    "add",
    "register_all",
]
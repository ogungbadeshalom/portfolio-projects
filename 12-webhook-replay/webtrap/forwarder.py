"""Live forwarding (mirror mode).

When a trap has a forward target configured, every captured request is both
stored locally *and* streamed to the target in real time. This lets you point
an integration at your local trap while still delivering the payload to the
real endpoint (a zero-config mirror).

Transport note
--------------
The forwarder accepts an injectable ``httpx`` transport so tests can hand it an
``httpx.ASGITransport`` wrapping an in-process echo app — full HTTP semantics
with no socket and no external service.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

#: Sentinel pushed into a job's stream queue to signal end-of-body.
_EOF = object()


class _ForwardJob:
    """A single in-flight streaming POST to a forward target.

    Chunks are fed into an :mod:`asyncio` queue from the capture loop; a
    background task reconstructs the request body from a generator so the body
    is never fully buffered before it is sent.
    """

    def __init__(
        self,
        url: str,
        *,
        method: str = "POST",
        headers: Optional[Dict[str, str]] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._url = url
        self._method = method
        self._headers = headers or {}
        self._transport = transport
        self._queue: "asyncio.Queue[Any]" = asyncio.Queue()
        self.response: Optional[httpx.Response] = None
        self._error: Optional[Exception] = None
        self._task = asyncio.create_task(self._run())

    async def feed(self, chunk: bytes) -> None:
        """Enqueue a body chunk to be forwarded."""
        if chunk:
            self._queue.put_nowait(chunk)

    async def close(self) -> Optional[httpx.Response]:
        """Signal end-of-body, wait for the send to finish, return response."""
        await self._queue.put(_EOF)
        try:
            await self._task
        except Exception:  # noqa: BLE001 - surfaced via self._error
            pass
        if self._error is not None:
            raise self._error
        return self.response

    async def _body_stream(self) -> AsyncIterator[bytes]:
        while True:
            item = await self._queue.get()
            if item is _EOF:
                return
            yield item

    async def _run(self) -> None:
        client_kwargs: Dict[str, Any] = {"timeout": httpx.Timeout(30.0)}
        if self._transport is not None:
            client_kwargs["transport"] = self._transport
        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                request = httpx.Request(
                    self._method, self._url, headers=self._headers, content=self._body_stream()
                )
                self.response = await client.send(request)
        except Exception as exc:  # noqa: BLE001 - record, don't crash capture
            self._error = exc
            logger.warning("Forward job to %s failed: %s", self._url, exc)


class Forwarder:
    """Registry of active streaming forward targets, keyed by trap token."""

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
        self._transport = transport
        self._targets: Dict[str, str] = {}  # token -> forward URL
        self._jobs: Dict[str, _ForwardJob] = {}

    # --- target registry --------------------------------------------------- #
    def set_target(self, token: str, url: str) -> None:
        """Configure a trap to mirror every captured request to ``url``."""
        self._targets[token] = url
        logger.info("Forward target set for token %r -> %s", token, url)

    def clear_target(self, token: str) -> Optional[str]:
        """Remove a trap's forward target, returning the old URL (if any)."""
        url = self._targets.pop(token, None)
        if url:
            logger.info("Forward target cleared for token %r", token)
        return url

    async def get_url(self, token: str) -> Optional[str]:
        """Return the configured forward URL for ``token`` or ``None``."""
        return self._targets.get(token)

    def has_target(self, token: str) -> bool:
        return token in self._targets

    # --- streaming push (called by the capture route) ---------------------- #
    async def push_chunk(self, token: str, chunk: bytes) -> None:
        """Stream ``chunk`` to the trap's forward target (no-op if not set)."""
        url = self._targets.get(token)
        if not url:
            return
        job = self._jobs.get(token)
        if job is None:
            job = _ForwardJob(url, transport=self._transport)
            self._jobs[token] = job
        await job.feed(chunk)

    async def finish(self, token: str) -> None:
        """Finalize and wait for the token's in-flight forward job."""
        job = self._jobs.pop(token, None)
        if job is not None:
            await job.close()


# Singleton used by the capture router / web UI. Tests may construct their own
# instance with an injected transport and swap it in.
_forwarder: Optional[Forwarder] = None
_default_transport: Optional[httpx.AsyncBaseTransport] = None


def set_forward_transport(transport: Optional[httpx.AsyncBaseTransport]) -> None:
    """Install a custom httpx transport for all new forward jobs (tests)."""
    global _default_transport
    _default_transport = transport


def get_forwarder() -> Forwarder:
    """Return the module-level singleton forwarder (created lazily)."""
    global _forwarder
    if _forwarder is None:
        _forwarder = Forwarder(transport=_default_transport)
    return _forwarder


def set_target_sync(token: str, url: str) -> None:
    """Configure a trap's forward target from synchronous code (CLI / route)."""
    get_forwarder().set_target(token, url)


def clear_target_sync(token: str) -> None:
    """Remove a trap's forward target from synchronous code."""
    get_forwarder().clear_target(token)


def forwards_snapshot() -> Dict[str, Optional[str]]:
    """Return a copy of the {token: url} forward-target map (sync, for UI)."""
    return dict(get_forwarder()._targets)


# --- the exact callables capture.py imports -------------------------------- #
async def get_forward_url(token: str) -> Optional[str]:
    """Return the configured forward URL for ``token`` (async, capture-facing)."""
    return await get_forwarder().get_url(token)


async def _push_forward_chunk(token: str, chunk: bytes) -> None:
    """Capture-facing hook: mirror one body chunk to the forward target."""
    await get_forwarder().push_chunk(token, chunk)


async def _finish_forward(token: str) -> None:
    """Capture-facing hook: finalize the mirror stream for ``token``."""
    await get_forwarder().finish(token)
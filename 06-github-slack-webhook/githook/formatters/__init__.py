"""Slack Block Kit formatters for supported GitHub webhook event types.

Each supported event type has a module under :mod:`githook.formatters` exposing
a ``format`` function that takes the parsed GitHub event payload and returns a
list of Slack Block Kit blocks (dicts).

A registry maps GitHub event names to formatter callables. Unknown or
uninteresting event types are mapped to ``None`` and are handled silently by the
webhook endpoint (GitHub always fires both ``X-GitHub-Event`` and the payload's
``action``; we support the four requested event *types* regardless of action).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from githook.formatters import push, pull_request, release, star

logger = logging.getLogger(__name__)

#: A formatter returns a list of Slack Block Kit blocks.
Formatter = Callable[[Dict[str, Any]], List[Dict[str, Any]]]

#: GitHub webhook event type -> formatter callable.
_FORMATTERS: Dict[str, Formatter] = {
    "push": push.format,
    "pull_request": pull_request.format,
    "release": release.format,
    "star": star.format,
}

#: Event types the notifier cares about. Everything else is "supported" and
#: answered with a silent 200 OK (per the spec).
SUPPORTED_EVENT_TYPES = frozenset(_FORMATTERS)
#: Alias kept for readability in webhook.py.
SUPPORTED = SUPPORTED_EVENT_TYPES


def get_formatter(event_type: str) -> Optional[Formatter]:
    """Return the formatter for ``event_type`` or ``None`` if unsupported."""
    return _FORMATTERS.get(event_type)


def format_event(event_type: str, payload: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """Return Block Kit blocks for an event, or ``None`` if not supported.

    Any formatting error is caught and logged; the caller then treats the event
    as unsupported (respond 200 OK without sending to Slack).
    """
    formatter = get_formatter(event_type)
    if formatter is None:
        return None
    try:
        return formatter(payload)
    except Exception:  # noqa: BLE001 - formatting must not crash the request
        logger.exception("Failed to format %r event payload.", event_type)
        return None
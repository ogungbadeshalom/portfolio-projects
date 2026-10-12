"""Input sanitization helpers for chat message text.

Message text is user-supplied and rendered into the browser, so we strip
markup before persisting/broadcasting. The policy here is deliberately
conservative: escape angle brackets so raw HTML is displayed inertly rather
than executed, and trim surrounding whitespace.
"""
from __future__ import annotations

import html
import re

# Only these tags survive a round-trip visually in a meaningful way; we simply
# neutralise every tag rather than maintain an allowlist, because chat text is
# plain text.
_TAG_RE = re.compile(r"<[^>]*>", re.IGNORECASE)


def sanitize(text: str) -> str:
    """Return a safe, length-trimmed version of a message string.

    Steps:
        1. Reject/neutralise tags (``<...>``) so no markup reaches the client.
        2. HTML-escape the result so the remainder is rendered as plain text.
        3. Collapse excessive whitespace and strip leading/trailing space.
    """
    if not isinstance(text, str):
        return ""
    # Remove anything that looks like an HTML tag first (covers ``<script>``).
    without_tags = _TAG_RE.sub("", text)
    # Escape the surviving text so any lone ``<``/``>`` stays inert.
    escaped = html.escape(without_tags, quote=True)
    # Normalise whitespace: squeeze multiple blank lines/spaces.
    cleaned = re.sub(r"[ \t]+", " ", escaped)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
"""Tag-based cache invalidation.

The heavy lifting lives on the storage backend (``delete_by_tag``); this module
adds the tag-matching semantics so ``APICache.invalidate_tag`` can be thin and
the behaviour testable in isolation.
"""
from __future__ import annotations

from typing import Sequence

from apicache.models import TAG_DELIMITER


def tags_match(entry_tags: Sequence[str], tag: str) -> bool:
    """Whether ``tag`` is one of ``entry_tags`` (exact, delimiter-safe)."""
    return tag in entry_tags


def serialize_tags(tags: Sequence[str]) -> str:
    """Join a sequence of tags onto the single TEXT column."""
    return TAG_DELIMITER.join(tags)


def deserialize_tags(delimited: str) -> list[str]:
    """Split a stored tag string back into its component tags."""
    if not delimited:
        return []
    return [t for t in delimited.split(TAG_DELIMITER) if t]
"""Short-code generation.

Produces URLs-safe, collision-resistant identifiers using the standard
library's ``secrets`` module (cryptographically strong randomness). Codes are
7 characters by default and designed to be resistant to guessing.
"""
from __future__ import annotations

import secrets
import string

#: Alphabet used for generated codes: URL-and-file-system-safe, no ambiguous
#: characters (0/O, 1/l, I) that could be confused when read aloud or copied.
ALPHABET = string.ascii_letters + string.digits
# Remove ambiguous characters for readability.
_AMBIGUOUS = set("0O1lI")
ALPHABET = "".join(c for c in ALPHABET if c not in _AMBIGUOUS)


def generate_code(length: int = 7) -> str:
    """Return a random URL-safe code of the given ``length``.

    Uses :func:`secrets.choice` so every code is drawn from a
    cryptographically strong source — short codes must be unguessable since
    they behave like public tokens.

    Args:
        length: Number of characters in the returned code.

    Returns:
        A ``length``-character string drawn from the safe alphabet.
    """
    if length < 1:
        raise ValueError("code length must be at least 1")
    return "".join(secrets.choice(ALPHABET) for _ in range(length))
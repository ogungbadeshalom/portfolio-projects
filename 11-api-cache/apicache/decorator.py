"""The ``@cached`` decorator with ``{arg}`` template expansion.

The decorated function must be ``async`` and its keyword/positional arguments
are exposed for template expansion in the cache key and tags. E.g.::

    @cache.cached(ttl=600, tags=["user-{user_id}"])
    async def fetch_user(user_id: int):
        return (await httpx.get(...)).json()

Calling ``fetch_user(42)`` reads/writes the key deriving from ``user_id=42``
and tags that entry with ``"user-42"``.
"""
from __future__ import annotations

import functools
import inspect
from typing import Any, Callable, Coroutine, Optional, Sequence, TypeVar

from apicache.config import validate_ttl

F = TypeVar("F", bound="Callable[..., Coroutine[Any, Any, Any]]")


class CachedFunction:
    """Wraps an async function so each call is served through the cache."""

    def __init__(
        self,
        func: F,
        *,
        cache: Any,
        ttl: Optional[float] = None,
        tags: Sequence[str] = (),
        key_prefix: str | None = None,
    ) -> None:
        self.func = func
        self._cache = cache
        self._ttl = validate_ttl(ttl)
        self._tags = list(tags or ())
        #: When None, a unique key is derived from the qualname + arguments.
        self.key_prefix = key_prefix
        functools.update_wrapper(self, func)
        self.__wrapped__ = func

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Fetch through the cache, calling through on a miss and storing."""
        context = self._bind_args(*args, **kwargs)
        key = self._make_key(context)
        tags = [self._expand(t, context) for t in self._tags]
        return await self._cache.get_or_fetch(
            key,
            fetcher=self._fetch_wrapper,
            ttl=self._ttl,
            tags=tags,
        )

    def _make_key(self, context: dict[str, Any]) -> str:
        """Produce the cache key.

        Uses the explicit ``key_prefix`` (with ``{arg}`` expansion) when one
        was supplied; otherwise the qualified name + a frozen representation
        of the bound arguments, so distinct calls get distinct keys.
        """
        if self.key_prefix is not None:
            return self._expand(self.key_prefix, context)
        suffix = self._freeze(context)
        return f"{self.func.__qualname__}:{suffix}"

    @staticmethod
    def _freeze(context: dict[str, Any]) -> str:
        """A stable string form of the bound-arguments dict."""
        # Sort keys so positional/keyword calls with the same params collide
        # consistently, then produce a compact repr.
        parts = [f"{k}={context[k]!r}" for k in sorted(context)]
        return ":".join(parts)

    async def _fetch_wrapper(self, key: str) -> Any:
        # ``key`` is ignored; we re-invoke the user function freshly.
        args, kwargs = self._current_call
        return await self.func(*args, **kwargs)

    def _bind_args(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Map the call's positional/keyword args to parameter names."""
        self._current_call = (args, kwargs)
        try:
            sig = inspect.signature(self.func)
            bound = sig.bind_partial(*args, **kwargs)
            bound.apply_defaults()
            return dict(bound.arguments)
        except (ValueError, TypeError):
            return {f"arg{i}": v for i, v in enumerate(args)} | kwargs

    @staticmethod
    def _expand(template: str, context: dict[str, Any]) -> str:
        """Replace ``{name}`` placeholders with values from ``context``."""
        result = template
        for key, value in context.items():
            result = result.replace("{" + str(key) + "}", str(value))
        return result


def cached(
    cache: Any,
    ttl: Optional[float] = None,
    tags: Sequence[str] = (),
    key_prefix: str | None = None,
) -> Callable[[F], CachedFunction]:
    """Decorator factory: cache an async function's return value.

    Args:
        cache: An :class:`apicache.APICache` instance (or compatible object).
        ttl: Override of the cache TTL for this function.
        tags: Tag templates (``{arg}`` supported) for group invalidation.
        key_prefix: Cache-key prefix; defaults to the function's qualified name.

    Returns:
        A decorator that returns a :class:`CachedFunction`.
    """

    def decorate(func: F) -> CachedFunction:
        return CachedFunction(
            func, cache=cache, ttl=ttl, tags=tags, key_prefix=key_prefix
        )

    return decorate
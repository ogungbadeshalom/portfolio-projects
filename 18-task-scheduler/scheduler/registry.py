"""Task function registry — the ``@task`` decorator.

Tasks are the callables workers execute. A task is registered with a name and
optionally an idempotency key extractor; workers look it up by name when a task
is dequeued. Keeping the registry in-process is exactly right for this
embedded scheduler and mirrors how Celery/Beat register app tasks.

Example
-------
>>> from scheduler.registry import task
>>> @task(name="send_email")
... def send_email(to: str):
...     return f"mailed {to}"
"""

from __future__ import annotations

import functools
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable


class TaskNotFoundError(KeyError):
    """Raised when a worker dequeues a task name with no registered handler."""


@dataclass
class TaskFunc:
    """Metadata + callable for a registered task."""

    name: str
    func: Callable[..., Any]
    timeout_seconds: float | None = None
    idempotency_fn: Callable[..., str | None] | None = field(default=None, repr=False)

    def run(self, payload: dict[str, Any]) -> Any:
        """Invoke the wrapped function with the task's payload dict."""
        return _call_with_payload(self.func, payload)


class Registry:
    """Name -> TaskFunc mapping, with decorator registration."""

    def __init__(self) -> None:
        self._tasks: dict[str, TaskFunc] = {}

    def task(
        self,
        name: str | None = None,
        *,
        timeout_seconds: float | None = None,
        idempotency_fn: Callable[..., str | None] | None = None,
    ) -> Callable[[Callable[..., Any]], TaskFunc]:
        """Decorator factory registering ``func`` under ``name``.

        ``name`` defaults to the function's qualified name. ``idempotency_fn``
        receives the payload and returns a stable key (or None) used to dedupe
        enqueues.
        """

        def deco(func: Callable[..., Any]) -> TaskFunc:
            task_name = name or f"{func.__module__}.{func.__qualname__}"
            if task_name in self._tasks:
                raise ValueError(f"task {task_name!r} already registered")
            entry = TaskFunc(
                name=task_name,
                func=func,
                timeout_seconds=timeout_seconds,
                idempotency_fn=idempotency_fn,
            )
            self._tasks[task_name] = entry
            return entry

        return deco

    def names(self) -> list[str]:
        return sorted(self._tasks)

    def get(self, name: str) -> TaskFunc:
        try:
            return self._tasks[name]
        except KeyError as exc:
            raise TaskNotFoundError(name) from exc

    def __contains__(self, name: str) -> bool:
        return name in self._tasks


#: Process-wide registry every worker shares.
registry = Registry()


def _call_with_payload(func: Callable[..., Any], payload: dict[str, Any]) -> Any:
    """Call ``func`` with ``payload`` items, ignoring unknown keys gracefully."""
    sig = inspect.signature(func)
    params = list(sig.parameters.values())
    accept_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params)
    positional_kwargs = [
        p.name
        for p in params
        if p.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
    ]
    if accept_kwargs:
        return func(**payload)
    call_kwargs = {k: payload[k] for k in positional_kwargs if k in payload}
    return func(**call_kwargs)


__all__ = ["Registry", "registry", "TaskFunc", "TaskNotFoundError", "task"]

#: Convenience pointing at the shared registry's decorator.
task = registry.task  # type: ignore[assignment]
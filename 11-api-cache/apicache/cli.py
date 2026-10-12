"""Command-line interface for :mod:`apicache`.

Usage (after ``pip install -e .``)::

    apicache stats
    apicache list
    apicache clear
    apicache clear --tag users
    apicache inspect user-123

Each command reads the database path from ``--db`` (default ``apicache.db``)
and drives the async cache through :func:`asyncio.run`.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Coroutine

import click

from apicache.config import resolve_db_path
from apicache.core import APICache

AsyncFn = Callable[[APICache], Coroutine[Any, Any, None]]


def _run(fn: AsyncFn, db_path: str) -> None:
    """Open a cache at ``db_path``, run ``fn(cache)``, and close it."""
    async def entry() -> None:
        cache = APICache(db_path)
        await cache.open()
        try:
            await fn(cache)
        finally:
            await cache.close()

    asyncio.run(entry())


@click.group()
@click.option(
    "--db",
    "db_path",
    default="apicache.db",
    show_default=True,
    help="Path to the cache SQLite database.",
)
@click.pass_context
def cli(ctx: click.Context, db_path: str) -> None:
    """JSON API → SQLite cache with TTL, tags, and ETags."""
    ctx.ensure_object(dict)
    ctx.obj["db_path"] = resolve_db_path(db_path)


@cli.command()
@click.pass_context
def stats(ctx: click.Context) -> None:
    """Show cache statistics."""
    db_path: str = ctx.obj["db_path"]

    async def body(cache: APICache) -> None:
        snapshot = await cache.stats()
        click.echo(f"hits            {snapshot.hits}")
        click.echo(f"misses          {snapshot.misses}")
        click.echo(f"hit_rate        {snapshot.hit_rate:.4f}")
        click.echo(f"miss_rate       {snapshot.miss_rate:.4f}")
        click.echo(f"total_entries   {snapshot.total_entries}")
        click.echo(f"expired_entries {snapshot.expired_entries}")
        click.echo(f"active_entries  {snapshot.active_entries}")

    _run(body, db_path)


@cli.command("list")
@click.pass_context
def list_keys(ctx: click.Context) -> None:
    """List all cache keys."""
    db_path: str = ctx.obj["db_path"]

    async def body(cache: APICache) -> None:
        keys = await cache.list_keys()
        if not keys:
            click.echo("(empty)")
            return
        for key in keys:
            click.echo(key)

    _run(body, db_path)


@cli.command()
@click.option("--tag", "tag", default=None, help="Clear only entries with this tag.")
@click.pass_context
def clear(ctx: click.Context, tag: str | None) -> None:
    """Clear all cached entries (or just those for ``--tag``)."""
    db_path: str = ctx.obj["db_path"]

    async def body(cache: APICache) -> None:
        if tag:
            removed = await cache.invalidate_tag(tag)
            click.echo(f"Removed {removed} entries tagged '{tag}'.")
        else:
            removed = await cache.clear()
            click.echo(f"Cleared {removed} entries.")

    _run(body, db_path)


@cli.command()
@click.argument("key")
@click.pass_context
def inspect(ctx: click.Context, key: str) -> None:
    """Show a single cache entry in detail."""
    db_path: str = ctx.obj["db_path"]

    async def body(cache: APICache) -> None:
        entry = await cache.inspect(key)
        if entry is None:
            click.echo(f"Key '{key}' not found.")
            return
        click.echo(f"key        {entry.key}")
        click.echo(f"created_at {entry.created_at:.3f}")
        click.echo(f"expires_at {entry.expires_at if entry.expires_at is not None else '(never)'}")
        click.echo(f"tags       {', '.join(entry.tags) or '(none)'}")
        click.echo(f"etag       {entry.etag or '(none)'}")
        click.echo("value      " + json.dumps(entry.value, ensure_ascii=False))

    _run(body, db_path)


def main() -> None:
    """Console entry point (``python -m apicache`` / ``apicache``)."""
    cli(prog_name="apicache")


if __name__ == "__main__":
    main()
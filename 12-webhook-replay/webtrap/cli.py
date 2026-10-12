"""Command-line interface for webtrap.

Implementation notes
--------------------
The CLI runs a private asyncio loop for the database and outbound httpx calls
(``asyncio.run`` per command), so a command is a self-contained process —
perfect for scripting. ``replay`` and ``forward`` accept the same transport
overrides the web layer does, so tests can drive a CLI-equivalent path fully
in-process.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, Dict, List, Optional

import click

from .database import get_session_factory, init_db


async def _show(session, request_id: int) -> Optional[str]:
    from .database import get_request

    record = await get_request(session, request_id)
    if record is None:
        return None
    return json.dumps(record.to_dict(), indent=2, default=str)


async def _list(session, limit: int) -> List[Dict[str, Any]]:
    from .database import count_requests, list_requests

    rows = await list_requests(session, limit=limit)
    return [r.to_dict() for r in rows]


@click.group()
@click.version_option()
def cli() -> None:
    """webtrap: capture, inspect, replay, and forward webhooks."""


@cli.command("start")
@click.option("--host", default="0.0.0.0", show_default=True, help="Bind host.")
@click.option("--port", default=8085, show_default=True, type=int, help="Bind port.")
def start(host: str, port: int) -> None:
    """Run the capture server + web UI (uvicorn)."""
    import uvicorn

    click.echo(f"webtrap listening on http://{host}:{port}")
    click.echo("Capture URL: http://<host>:{p}/incoming/<token>".format(p=port))
    uvicorn.run("webtrap.main:app", host=host, port=port, reload=False)


@cli.command("list")
@click.option("--limit", default=50, type=int, show_default=True)
def list_cmd(limit: int) -> None:
    """List captured requests (newest first)."""
    init_db()
    async def _run():
        async with get_session_factory()() as session:
            return await _list(session, limit)
    rows = asyncio.run(_run())
    for r in rows:
        click.echo(f"#{r['id']:<5} {r['method']:<6} token={r['token']:<10} {r['path']}")


@cli.command("show")
@click.argument("request_id", type=int)
def show_cmd(request_id: int) -> None:
    """Inspect a captured request (full headers + body)."""
    init_db()
    async def _run():
        async with get_session_factory()() as session:
            return await _show(session, request_id)
    data = asyncio.run(_run())
    if data is None:
        raise click.ClickException(f"No request #{request_id}")
    click.echo(data)


@cli.command("replay")
@click.argument("request_id", type=int)
@click.option("--target", required=True, help="Target base URL, e.g. https://prod.example.com")
@click.option("--delay", default=0, type=int, help="Delay in milliseconds before sending.")
def replay_cmd(request_id: int, target: str, delay: int) -> None:
    """Replay a captured request against a target URL."""
    from .replay import replay_request

    init_db()
    async def _run():
        async with get_session_factory()() as session:
            return await replay_request(session, request_id, target=target, delay_ms=delay)
    result = asyncio.run(_run())
    if result is None:
        raise click.ClickException(f"No request #{request_id}")
    click.echo(f"HTTP {result.status_code}")
    click.echo(json.dumps(result.to_dict(), default=str))


@cli.command("forward")
@click.argument("url")
@click.option("--token", default="demo", help="Trap token whose mirror target to set.")
def forward_cmd(url: str, token: str) -> None:
    """Configure live forward mode: capture AND mirror to a real endpoint."""
    from .forwarder import set_target_sync

    set_target_sync(token, url)
    click.echo(f"Forward target for token '{token}' set to {url}")


@cli.command("trap")
@click.option("--forward-url", default=None, help="Optional mirror target URL.")
def trap_cmd(forward_url: Optional[str]) -> None:
    """Generate a fresh trap token (optionally with a forward target)."""
    import secrets

    from .forwarder import set_target_sync

    token = secrets.token_urlsafe(8)
    if forward_url:
        set_target_sync(token, forward_url)
        click.echo(f"trap {token!r} -> forward {forward_url}")
    else:
        click.echo(f"trap {token!r} -> local capture only")


@cli.command()
def health() -> None:
    """Quick DB sanity check."""
    init_db()
    click.echo("DB engine initialised OK")


if __name__ == "__main__":
    cli()
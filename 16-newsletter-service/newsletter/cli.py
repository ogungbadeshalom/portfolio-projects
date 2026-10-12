"""Click command-line interface for the newsletter service.

Runnable standalone via ``python -m newsletter.cli`` or the installed
``newsletter`` entry point. Subcommands per the project spec:

    newsletter init
    newsletter subscribe EMAIL [--name NAME]
    newsletter list [--status STATUS]
    newsletter campaign new "SUBJECT"
    newsletter campaign list
    newsletter campaign send CAMPAIGN_ID
    newsletter stats
    newsletter export            # dump subscribers as CSV to stdout

The CLI shares the exact same logic as the web API: each subcommand opens a
fresh :class:`AsyncSession` inside its own ``asyncio.run`` call and drives the
async helpers directly, so behavior stays consistent across entry points.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import click

from newsletter.config import settings
from newsletter.db import AsyncSessionLocal, init_db
from newsletter.models import SubscriberStatus


# --- async bridge -------------------------------------------------------------

def _run(coro_factory) -> object:
    """Run an async helper against a fresh async session in one synchronous call.

    ``asyncio.run`` creates a clean event loop per call, which is what makes each
    CLI subcommand standalone-safe (no shared loop state between commands).
    """
    return asyncio.run(coro_factory())


async def _subscribe_async(email: str, name: Optional[str]):
    from newsletter.subscribe import subscribe

    async with AsyncSessionLocal() as session:
        return await subscribe(session, email, name=name)


async def _list_async(status: Optional[str]):
    from newsletter.campaigns import list_subscribers

    async with AsyncSessionLocal() as session:
        return await list_subscribers(session, status=status)


async def _stats_async():
    from newsletter.campaigns import get_global_stats

    async with AsyncSessionLocal() as session:
        return await get_global_stats(session)


async def _campaign_new_async(subject: str, html: str, text: str):
    from newsletter.campaigns import create_campaign

    async with AsyncSessionLocal() as session:
        return await create_campaign(session, subject, html_body=html, text_body=text)


async def _campaign_send_async(campaign_id: int):
    from newsletter.campaigns import get_campaign
    from newsletter.sender import send_campaign

    async with AsyncSessionLocal() as session:
        campaign = await get_campaign(session, campaign_id)
        if campaign is None:
            raise click.ClickException(f"Campaign {campaign_id} not found.")
        await send_campaign(session, campaign, rate_limit=settings.rate_per_min)
        return campaign


async def _campaign_list_async():
    from newsletter.campaigns import list_campaigns

    async with AsyncSessionLocal() as session:
        return await list_campaigns(session)


# --- main group ---------------------------------------------------------------

@click.group()
@click.version_option(version="0.1.0", prog_name="newsletter")
def main() -> None:
    """Newsletter Service - manage subscribers, campaigns and stats."""


# --- init ---------------------------------------------------------------------

@main.command()
def init() -> None:
    """Create tables if missing."""
    init_db()
    click.echo("Initialized database.")
    click.echo(f"  Admin user:     {settings.admin_user}")
    click.echo("  Admin password: (see NEWSLETTER_ADMIN_PASSWORD env / config)")


# --- subscribe ----------------------------------------------------------------

@main.command()
@click.argument("email")
@click.option("--name", default=None, help="Subscriber's display name.")
def subscribe(email: str, name: Optional[str]) -> None:
    """Register a new subscriber (double opt-in confirmation email is sent)."""
    init_db()
    sub = _run(lambda: _subscribe_async(email, name))
    click.echo(f"Subscribed {sub.email} [status={sub.status}] (confirmation email sent).")


# --- list ---------------------------------------------------------------------

@main.command("list")
@click.option("--status", default=None, type=click.Choice(
    [s.value for s in SubscriberStatus]))
def list_cmd(status: Optional[str]) -> None:
    """List all subscribers (optionally filtered by status)."""
    init_db()
    rows = _run(lambda: _list_async(status))
    if not rows:
        click.echo("No subscribers.")
        return
    width = max((len(r.email) for r in rows), default=0)
    for r in rows:
        click.echo(f"{r.id:>3}  {r.email:<{width}}  {r.status:<14} {r.name or ''}")


# --- campaign group -----------------------------------------------------------

@main.group()
def campaign() -> None:
    """Campaign management."""
    init_db()


@campaign.command("new")
@click.argument("subject")
@click.option("--html", default="", help="HTML body (optional).")
@click.option("--text", default="", help="Plaintext body (optional).")
def campaign_new(subject: str, html: str, text: str) -> None:
    """Create a new draft campaign."""
    c = _run(lambda: _campaign_new_async(subject, html, text))
    click.echo(f"Created campaign #{c.id}: {c.subject} [{c.status}]")


@campaign.command("list")
def campaign_list() -> None:
    """List all campaigns."""
    rows = _run(_campaign_list_async)
    if not rows:
        click.echo("No campaigns.")
        return
    for c in rows:
        sent = c.sent_at.isoformat() if c.sent_at else "-"
        click.echo(f"#{c.id}  {c.subject:<40} {c.status:<10} sent_at={sent}")


@campaign.command("send")
@click.argument("campaign_id", type=int)
def campaign_send(campaign_id: int) -> None:
    """Send a campaign to every ACTIVE subscriber (rate-limited)."""
    campaign = _run(lambda: _campaign_send_async(campaign_id))
    click.echo(
        f"Campaign #{campaign.id} sent to active subscribers "
        f"[status={campaign.status} sent_at={campaign.sent_at.isoformat() if campaign.sent_at else '-'}]."
    )


# --- stats --------------------------------------------------------------------

@main.command()
def stats() -> None:
    """Show global stats (subscribers, sends, opens, clicks)."""
    init_db()
    s = _run(_stats_async)
    click.echo(f"Subscribers : {s['subscribers']} (active={s['active']}, "
               f"pending={s['pending']}, unsubscribed={s['unsubscribed']})")
    click.echo(f"Sends       : {s['sent']}")
    click.echo(f"Opens       : {s['opened']}")
    click.echo(f"Clicks      : {s['clicked']}")


# --- export -------------------------------------------------------------------

@main.command()
@click.option("--status", default=None, type=click.Choice(
    [s.value for s in SubscriberStatus]))
def export(status: Optional[str]) -> None:
    """Dump subscribers as CSV to stdout."""
    init_db()
    from newsletter.campaigns import subscribers_to_csv

    rows = _run(lambda: _list_async(status))
    click.echo(subscribers_to_csv(rows).rstrip())


if __name__ == "__main__":
    main()
"""Click command-line interface for the cron watchdog.

The CLI talks to the same SQLite store the dashboard uses (see the
``Verification`` section of ``CLAUDE.md``), so ``start``/``done`` written here
show up instantly in the dashboard. No separate server round-trip is required,
which keeps local usage simple and test-friendly.

Commands
--------
* ``init`` — print / create the API key.
* ``schedule job --name ... --cron ...`` — register a job.
* ``start job --client-run-id`` — open a run.
* ``ping job-or-runid`` — heartbeat a live run.
* ``done job-or-runid --status`` — close a run (ok/fail), alerting on fail.
* ``list`` — list jobs.
* ``watchdog`  — run one dead-man's-switch sweep.

Exit codes: 0 success, 1 error (job missing, invalid input).
"""

from __future__ import annotations

import logging
import sys

import click

from cronmon import auth
from cronmon.alerting import dispatch
from cronmon.database import SessionLocal, init_db
from cronmon.models import Alert, Job, Run, now_utc
from cronmon.watchdog import check as watchdog_check

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("cronmon.cli")


@click.group()
@click.option(
    "--db",
    default=None,
    help="Path to the cronmon sqlite DB (default: env CRONMON_DB or :memory:).",
)
@click.pass_context
def cli(ctx: click.Context, db: str | None) -> None:
    """Watchdog CLI — register jobs, record run lifecycles, sweep for alerts."""
    ctx.ensure_object(dict)
    if db:
        import os

        os.environ["CRONMON_DB"] = db
    init_db(seed=True)
    ctx.obj["session"] = SessionLocal()


@cli.command()
def init() -> None:
    """Print the API key used to authorize CLI/HTTP calls."""
    key = auth.load_or_create_key()
    click.echo(f"API key: {key}")
    click.echo(f"fingerprint: {auth.fingerprint(key)}")
    click.echo("Send it in the X-API-Key header for HTTP run mutations.")


@cli.command()
@click.argument("job_name")
@click.option("--name", default=None, help="Register under a different name.")
@click.option("--cron", default=None, help="5-field cron schedule, e.g. '0 2 * * *'.")
@click.option("--max-duration", "expected_duration", default=3600, type=int,
              help="Max seconds a run may last before the watchdog flags it.")
@click.option("--alert-after", "alert_after_minutes", default=120, type=int,
              help="Minutes past next fire before a missed-schedule alert.")
@click.option("--webhook", default=None, help="POST alerts to this URL.")
@click.pass_context
def schedule(
    ctx: click.Context,
    job_name: str,
    name: str | None,
    cron: str | None,
    expected_duration: int,
    alert_after_minutes: int,
    webhook: str | None,
) -> None:
    """Register a job (by name or id) with an optional cron schedule."""
    db = ctx.obj["session"]
    ident = name or job_name
    existing = db.query(Job).filter(Job.name == ident).first()
    if existing:
        existing.cron = cron or existing.cron
        existing.expected_duration = expected_duration
        existing.alert_after_minutes = alert_after_minutes
        if webhook:
            existing.webhook_url = webhook
        db.commit()
        click.echo(f"Updated job {ident!r} (id={existing.id}).")
        return
    job = Job(
        name=ident,
        cron=cron,
        expected_duration=expected_duration,
        alert_after_minutes=alert_after_minutes,
        webhook_url=webhook,
    )
    db.add(job)
    db.commit()
    click.echo(f"Registered job {ident!r} (id={job.id}).")


@cli.command()
@click.argument("job_ref")
@click.option("--client-run-id", default=None, help="Dedup key for at-least-once starts.")
@click.pass_context
def start(ctx: click.Context, job_ref: str, client_run_id: str | None) -> None:
    """Open a new run for a job (by name or id)."""
    db = ctx.obj["session"]
    job = _find_job(db, job_ref)
    if job is None:
        click.echo(f"Unknown job {job_ref!r} — run `watchdog schedule` first.", err=True)
        sys.exit(1)
    if client_run_id:
        existing = (
            db.query(Run)
            .filter(Run.job_id == job.id, Run.client_run_id == client_run_id)
            .first()
        )
        if existing:
            click.echo(f"Reusing run #{existing.id} for {job.name!r} (dedup).")
            return
    run = Run(job_id=job.id, pinged_at=now_utc(), status="running", client_run_id=client_run_id)
    db.add(run)
    db.commit()
    click.echo(f"Started run #{run.id} for {job.name!r}.")


@cli.command()
@click.argument("run_ref")
@click.pass_context
def ping(ctx: click.Context, run_ref: str) -> None:
    """Send a heartbeat for a live run (by run id or the job name)."""
    db = ctx.obj["session"]
    run = _find_run(db, run_ref)
    if run is None:
        click.echo(f"No live run for {run_ref!r}.", err=True)
        sys.exit(1)
    run.pinged_at = now_utc()
    db.commit()
    click.echo(f"Pinged run #{run.id} (heartbeat {run.pinged_at.isoformat()}).")


@cli.command()
@click.argument("run_ref")
@click.option("--status", "status", type=click.Choice(["ok", "fail"]), default="ok")
@click.pass_context
def done(ctx: click.Context, run_ref: str, status: str) -> None:
    """Close a live run with a final status. 'fail' raises an alert."""
    db = ctx.obj["session"]
    run = _find_run(db, run_ref)
    if run is None:
        click.echo(f"No live run for {run_ref!r}.", err=True)
        sys.exit(1)
    if run.ended_at is not None:
        click.echo(f"Run #{run.id} already finished ({run.status}).")
        return
    run.ended_at = now_utc()
    run.status = status
    db.commit()
    click.echo(f"Finished run #{run.id} with status '{status}'.")

    if status == "fail":
        job = db.get(Job, run.job_id)
        alert = Alert(
            job_id=job.id,
            run_id=run.id,
            type="run_failed",
            message=f"Job {job.name!r} finished with status 'fail' "
            f"(duration {run.duration_seconds}s).",
        )
        db.add(alert)
        db.commit()
        delivered = dispatch(db, alert)
        click.echo(
            f"Raised alert #{alert.id} for {job.name!r}"
            + (" (webhook sent)." if delivered else " (no webhook).")
        )


@cli.command(name="list")
@click.pass_context
def list_jobs(ctx: click.Context) -> None:
    """List all registered jobs."""
    db = ctx.obj["session"]
    rows = db.query(Job).order_by(Job.name).all()
    if not rows:
        click.echo("No jobs registered.")
        return
    for job in rows:
        click.echo(f"#{job.id:<4} {job.name:<24} cron={job.cron or '-':<12} "
                   f"max={job.expected_duration or '-'}")
    click.echo(f"\n{len(rows)} job(s)")


@cli.command()
@click.pass_context
def watchdog(ctx: click.Context) -> None:
    """Run one dead-man's-switch + over-duration sweep now."""
    db = ctx.obj["session"]
    created = watchdog_check(db)
    click.echo(f"Watchdog sweep complete — {created} new alert(s).")


def _find_job(db, ref: str) -> Job | None:
    if ref.isdigit():
        return db.get(Job, int(ref))
    return db.query(Job).filter(Job.name == ref).first()


def _find_run(db, ref: str) -> Run | None:
    """Resolve a run ref: a numeric run id first, else the latest live run of a job name."""
    if ref.isdigit():
        run = db.get(Run, int(ref))
        if run is not None and run.ended_at is None:
            return run
    job = _find_job(db, ref)
    if job is None:
        return None
    return (
        db.query(Run)
        .filter(Run.job_id == job.id, Run.ended_at.is_(None))
        .order_by(Run.started_at.desc())
        .first()
    )


if __name__ == "__main__":
    cli()
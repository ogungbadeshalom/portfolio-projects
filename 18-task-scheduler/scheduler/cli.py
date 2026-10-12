"""Click CLI for the task scheduler.

Commands mirror CLAUDE.md:

    scheduler schedule "send_email" --at "ISO" --payload '{"to":"..."}'
    scheduler schedule "cleanup" --cron "0 * * * *" --payload '{}'
    scheduler list
    scheduler show TASK_ID
    scheduler cancel TASK_ID
    scheduler retry TASK_ID
    scheduler dlq

Each invocation reads/writes the shared sqlite store (via ``--db`` or
``SCHEDULER_DB``) exactly like the FastAPI app, so CLI and web agree. The CLI
does NOT start workers; use ``python -m scheduler.worker`` or the server for
execution.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime

import click

from scheduler import example_tasks  # noqa: F401  (registers handlers)
from scheduler import service
from scheduler.config import get_config, reset_config
from scheduler.dlq import list_dlq, retry_dlq
from scheduler.registry import registry
from scheduler.store import get_session
from scheduler.models import Task, STATUS_PENDING

logging.basicConfig(level=logging.WARNING)


def _parse_payload(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"payload is not valid JSON: {exc}") from exc


def _parse_at(raw: str | None) -> datetime | None:
    if not raw or raw.lower() in {"now", "asap"}:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise click.ClickException(f"invalid --at timestamp: {raw!r}") from exc


@click.group()
@click.option("--db", default=None, help="Path to the sqlite store (or SCHEDULER_DB).")
@click.pass_context
def cli(ctx: click.Context, db: str | None) -> None:
    """Distributed task scheduler CLI."""
    ctx.ensure_object(dict)
    import os

    if db:
        # Explicit --db always wins and rebuilds the store for THIS file, so a
        # call never inherits the engine a previous invocation left behind.
        resolved = db
    elif os.getenv("SCHEDULER_DB"):
        resolved = os.environ["SCHEDULER_DB"]
    else:
        # Persist to a default file so CLI runs and the server share state.
        resolved = str(get_config().data_dir / "scheduler.db")
    os.environ["SCHEDULER_DB"] = resolved
    reset_config()
    from scheduler.store import init_store

    init_store(resolved)


@cli.command()
@click.argument("name")
@click.option("--at", "at_raw", default=None, help="One-shot ISO time or 'now'.")
@click.option("--cron", default=None, help="5-field cron expression for recurrence.")
@click.option("--payload", default=None, help="JSON payload dict for the task.")
@click.option("--max-attempts", "max_attempts", type=int, default=None)
@click.option("--idempotency-key", "idempotency_key", default=None)
def schedule(
    name: str,
    at_raw: str,
    cron: str,
    payload: str,
    max_attempts: int | None,
    idempotency_key: str | None,
) -> None:
    """Schedule a task for execution."""
    if name not in registry:
        click.echo(
            f"Unknown task {name!r}. Registered: {registry.names()}", err=True
        )
        sys.exit(1)
    try:
        task = service.schedule_task(
            name,
            payload=_parse_payload(payload),
            at=_parse_at(at_raw),
            cron_expr=cron,
            max_attempts=max_attempts,
            idempotency_key=idempotency_key,
        )
    except service.TaskError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"Scheduled task #{task.id} '{task.name}' "
        f"[{task.status}] at={task.scheduled_at} cron={task.cron or '-'}"
    )


@cli.command(name="list")
def list_tasks() -> None:
    """List all tasks."""
    session = get_session()
    try:
        rows = session.query(Task).order_by(Task.created_at.desc()).limit(100).all()
        if not rows:
            click.echo("No tasks.")
            return
        for t in rows:
            click.echo(
                f"#{t.id:<4} {t.name:<16} {t.status:<8} "
                f"at={t.scheduled_at.strftime('%m-%d %H:%M') if t.scheduled_at else '-':<16} "
                f"cron={t.cron or '-':<14} attempts={t.attempts}/{t.max_attempts}"
            )
        click.echo(f"\n{len(rows)} task(s)")
    finally:
        session.close()


@cli.command()
@click.argument("task_id", type=int)
def show(task_id: int) -> None:
    """Show task details + run history."""
    session = get_session()
    try:
        task = session.get(Task, task_id)
        if task is None:
            raise click.ClickException(f"task #{task_id} not found")
        summary = service.task_summary(session, task)
        click.echo(f"Task #{summary['id']} — {summary['name']}")
        click.echo(f"  status: {summary['status']}  attempts: {summary['attempts']}/{summary['max_attempts']}")
        click.echo(f"  scheduled_at: {summary['scheduled_at']}  cron: {summary['cron'] or '-'}")
        click.echo(f"  payload: {summary['payload_json']}")
        if summary["last_error"]:
            click.echo(f"  last_error: {summary['last_error'][:400]}")
        for r in summary["runs"]:
            click.echo(
                f"  run #{r['id']} worker={r['worker_id']} {r['status']} "
                f"{r['duration_seconds'] or '?'}s"
            )
    finally:
        session.close()


@cli.command()
@click.argument("task_id", type=int)
def cancel(task_id: int) -> None:
    """Cancel a pending task."""
    if service.cancel_task(task_id):
        click.echo(f"Canceled task #{task_id}.")
    else:
        raise click.ClickException(f"task #{task_id} not pending or missing")


@cli.command()
@click.argument("task_id", type=int)
def retry(task_id: int) -> None:
    """Re-enqueue a dead-lettered task."""
    if retry_dlq(task_id):
        click.echo(f"Re-enqueued task #{task_id} for retry.")
    else:
        raise click.ClickException(f"task #{task_id} is not in the DLQ")


@cli.command()
def dlq() -> None:
    """Show the dead-letter queue."""
    rows = list_dlq()
    if not rows:
        click.echo("DLQ is empty.")
        return
    for d in rows:
        click.echo(f"#{d['id']:<4} {d['name']:<16} attempts={d['attempts']}/{d['max_attempts']}")
        if d["last_error"]:
            click.echo(f"       error: {d['last_error'][:160]}")


@cli.command()
def tasks() -> None:
    """List registered task handlers."""
    for name in registry.names():
        click.echo(f"  {name}")
    click.echo(f"\n{len(registry.names())} handler(s)")


if __name__ == "__main__":
    cli()
"""Command-line interface for the transcoder queue.

The CLI is a thin client of the FastAPI server::

    transcoder submit video.mp4 --resolutions 480,720,1080
    transcoder list
    transcoder status JOB_ID
    transcoder watch JOB_ID          # live progress via WebSocket
    transcoder serve                 # run the server

Uses Click when available, else an argparse fallback.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from . import __version__

try:  # pragma: no cover - import-style guard
    import click

    _HAS_CLICK = True
except Exception:  # noqa: BLE001
    click = None
    _HAS_CLICK = False

DEFAULT_BASE = "http://127.0.0.1:8080"


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #


def _api_base() -> str:
    import os
    return os.environ.get("TRANSCODER_BASE", DEFAULT_BASE).rstrip("/")


def _submit(path: str, resolutions: str) -> dict:
    """POST a file to the running server and return the created job."""
    import httpx

    with open(path, "rb") as fh:
        resp = httpx.post(
            f"{_api_base()}/api/jobs",
            files={"file": (Path(path).name, fh, "video/mp4")},
            data={"resolutions": resolutions},
            timeout=60.0,
        )
    resp.raise_for_status()
    return resp.json()


def _status(job_id: str) -> dict:
    import httpx

    resp = httpx.get(f"{_api_base()}/api/jobs/{job_id}", timeout=5.0)
    resp.raise_for_status()
    return resp.json()


def _list(status: str | None) -> list[dict]:
    import httpx

    params = {}
    if status:
        params["status"] = status
    resp = httpx.get(f"{_api_base()}/api/jobs", params=params, timeout=5.0)
    resp.raise_for_status()
    return resp.json()["jobs"]


def _watch(job_id: str) -> None:
    """Stream progress events for ``job_id`` until the job goes terminal."""
    import websockets

    ws_url = _api_base().replace("http", "ws") + f"/ws/jobs/{job_id}"

    async def _inner():
        try:
            _status(job_id)
        except Exception:  # noqa: BLE001
            print(f"Job {job_id} not found or server unreachable at {_api_base()}.")
            return
        async with websockets.connect(ws_url) as ws:
            async for raw in ws:
                ev = json.loads(raw)
                if ev.get("type") == "progress":
                    print(f"\r{ev['job_id']}  {ev['progress_pct']:5.1f}%", end="", flush=True)
                elif ev.get("type") == "job":
                    print(f"\r{ev['job_id']}  {ev.get('status'):>9}  {ev.get('progress_pct')}%")
                    if ev.get("status") in ("completed", "failed", "cancelled"):
                        break
        print()

    asyncio.run(_inner())


# --------------------------------------------------------------------------- #
# Click group
# --------------------------------------------------------------------------- #


def _make_click():
    @click.group()
    @click.version_option(__version__)
    def cli():
        """Video Transcoder Queue (FFmpeg)."""

    @cli.command()
    @click.argument("path", type=click.Path(exists=True))
    @click.option("--resolutions", default="480,720,1080", show_default=True)
    def submit(path, resolutions):
        """Submit a video for transcoding."""
        result = _submit(path, resolutions)
        click.echo(
            f"Submitted job {result['id']} "
            f"resolutions={result['resolutions']} ({_api_base()})"
        )

    @cli.command()
    @click.option("--status", default=None, help="Filter: queued/processing/completed/failed.")
    def list(status):
        """List jobs (optionally filtered by status)."""
        for j in _list(status):
            click.echo(f"{j['id']}\t{j['filename'][:40]}\t{j['status']}\t{j['progress_pct']}%")

    @cli.command()
    @click.argument("job_id")
    def status(job_id):
        """Show a single job's status."""
        j = _status(job_id)
        click.echo(json.dumps(j, indent=2, default=str))

    @cli.command()
    @click.argument("job_id")
    def watch(job_id):
        """Stream live progress for a job via WebSocket."""
        _watch(job_id)

    @cli.command()
    @click.option("--port", default=8080, show_default=True)
    @click.option("--reload", is_flag=True, default=False)
    def serve(port, reload):
        """Run the FastAPI server."""
        import uvicorn

        uvicorn.run("transcoder.main:app", host="0.0.0.0", port=port, reload=reload)

    return cli


# --------------------------------------------------------------------------- #
# argparse fallback
# --------------------------------------------------------------------------- #


def _make_argparse() -> int:
    import argparse

    p = argparse.ArgumentParser(prog="transcoder", description="Video transcoder queue")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("submit", help="Submit a video")
    s.add_argument("path")
    s.add_argument("--resolutions", default="480,720,1080")
    s.set_defaults(func=lambda a: print(_submit(a.path, a.resolutions)))

    l = sub.add_parser("list", help="List jobs")
    l.add_argument("--status", default=None)
    l.set_defaults(func=lambda a: [print(
        f"{j['id']}\t{j['filename'][:40]}\t{j['status']}\t{j['progress_pct']}%"
    ) for j in _list(a.status)])

    st = sub.add_parser("status", help="Job status")
    st.add_argument("job_id")
    st.set_defaults(func=lambda a: print(json.dumps(_status(a.job_id), indent=2, default=str)))

    w = sub.add_parser("watch", help="Live progress")
    w.add_argument("job_id")
    w.set_defaults(func=lambda a: _watch(a.job_id))

    sv = sub.add_parser("serve", help="Run server")
    sv.add_argument("--port", default=8080, type=int)
    sv.set_defaults(func=lambda a: _serve_argparse(a.port))

    args = p.parse_args()
    args.func(args)
    return 0


def _serve_argparse(port: int) -> None:
    import uvicorn

    uvicorn.run("transcoder.main:app", port=port)


def make_cli():
    """Return the Click command group (or argparse wrapper) for the CLI."""
    if _HAS_CLICK:
        return _make_click()
    return _make_argparse()  # type: ignore[return-value]  # argparse path prints directly


def main(argv=None) -> int:  # pragma: no cover - thin wrapper
    if _HAS_CLICK:
        cli = _make_click()
        if argv is None:
            cli(obj=None)
        else:
            cli.main(args=list(argv), prog_name="transcoder")
        return 0
    if argv is not None:
        sys.argv[:] = ["transcoder", *argv]
    return _make_argparse()


if __name__ == "__main__":
    raise SystemExit(main())
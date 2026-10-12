"""Asyncio job queue that runs FFmpeg transcodes in the background.

The queue owns a single worker coroutine that pulls jobs off a FIFO and
processes up to :data:`transcoder.config.MAX_CONCURRENT` at once.  Progress
is streamed to *subscribers* (one per job id) so the WebSocket endpoint and
the polling API stay in sync with transient in-memory state, while durable
state lives in the database.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Awaitable, Callable, Optional

from . import config, models, transcoder as ff
from .models import JobStatus

logger = logging.getLogger(__name__)

#: Subscriber queue type; ``None`` means a closed/removed subscriber.
Subscriber = asyncio.Queue

#: Called with a dict when job state changes (status / progress / files).
JobEventCallback = Callable[[dict], None]


class JobQueue:
    """Process video jobs with a bounded concurrency and retries.

    This is deliberately dependency-free of FastAPI: routes push jobs into it
    and the app starts/stops it on its lifespan.  The in-memory ``_subscribers``
    map lets the WebSocket manager relay progress without polling the DB.
    """

    def __init__(
        self,
        session_factory,
        *,
        max_workers: int = config.MAX_CONCURRENT,
        max_retries: int = config.MAX_RETRIES,
        on_event: Optional[JobEventCallback] = None,
    ) -> None:
        self._session_factory = session_factory
        self.max_workers = max_workers
        self.max_retries = max_retries
        self._on_event = on_event or (lambda ev: None)
        self._jobs: "asyncio.Queue[str]" = asyncio.Queue()
        self._active_task: Optional[asyncio.Task] = None
        self._workers: list[asyncio.Task] = []
        self._subscribers: dict[str, asyncio.Queue] = {}
        # Keep event-loop coupling minimal: tasks are started by start().
        self._started = False

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        """Spawn the worker pool (idempotent).  Must be called on the loop."""
        if self._started:
            return
        self._started = True
        self._active_task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Cancel the worker pool and wait for in-flight work to unwind."""
        if not self._started:
            return
        self._started = False
        if self._active_task:
            self._active_task.cancel()
            try:
                await self._active_task
            except asyncio.CancelledError:
                pass
        self._active_task = None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def enqueue(self, job_id: str) -> None:
        """Add a job id to the queue (no-op if already present/pending)."""
        self._jobs.put_nowait(job_id)

    def close_subscriber(self, job_id: str) -> None:
        """Drop a subscriber queue (e.g. when a WebSocket disconnects)."""
        self._subscribers.pop(job_id, None)

    async def wait_for_job(self, job_id: str) -> Subscriber:
        """Return a queue that will receive events for ``job_id``."""
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers[job_id] = q
        return q

    def publish(self, event: dict) -> None:
        """Broadcast ``event`` to the job's subscriber (if any) and callback."""
        self._on_event(event)
        job_id = event.get("job_id")
        if not job_id:
            return
        q = self._subscribers.get(job_id)
        if q is not None:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:  # pragma: no cover - defensive
                pass

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    async def _run(self) -> None:
        """Persistent dispatcher: keeps populating workers until stopped."""
        try:
            while self._started:
                job_id = await self._jobs.get()
                # Gate concurrency with a slim semaphore per in-flight worker.
                while len(self._workers) >= self.max_workers:
                    # Await the oldest worker slot to free up.
                    done, _ = await asyncio.wait(
                        self._workers, return_when=asyncio.FIRST_COMPLETED
                    )
                    self._workers = [t for t in self._workers if not t.done()]
                task = asyncio.create_task(self._process(job_id))
                self._workers.append(task)
        except asyncio.CancelledError:
            for t in self._workers:
                t.cancel()
            raise

    async def _process(self, job_id: str) -> None:
        """Run a single job with retry-on-transient-failure semantics."""
        session = self._session_factory()
        try:
            job = models.get_job(session, job_id)
            if job is None:
                return
            if job.status in (JobStatus.FAILED, JobStatus.CANCELLED):
                return
            job.status = JobStatus.PROCESSING
            job.attempts = (job.attempts or 0) + 1
            session.commit()

            heights = [
                r.height
                for r in sorted(job.resolutions, key=lambda r: r.height)
            ]
            if not heights:
                heights = config.RESOLUTIONS

            self._publish_job(session, job_id)

            def report(pct: float) -> None:
                # Update job row progress live (cheap DB check per tick).
                with session.begin():
                    cur = models.get_job(session, job_id)
                    if cur is None:
                        return
                    cur.progress_pct = round(pct, 1)
                self._publish_progress(session, job_id, pct)

            job_dir = config.OUTPUT_DIR / job_id
            result = await ff.transcode(
                job.source_path, job_dir, heights, on_progress=report
            )

            # Write a multi-resolution master playlist that references each
            # variant playlist (with bandwidth hints), per the HLS spec.
            from . import hls
            stubs = []
            for res in sorted(heights):
                variant = job_dir / f"{res}p" / "playlist.m3u8"
                if variant.exists():
                    stubs.append((res, f"{res}p/playlist.m3u8"))
            if stubs:
                (job_dir / "master.m3u8").write_text(
                    hls.master_playlist(stubs), encoding="utf-8"
                )

            # Mark resolutions complete, record produced files.
            with session.begin():
                fresh = models.get_job(session, job_id)
                if fresh is None:
                    return
                for res in fresh.resolutions:
                    res.status = JobStatus.COMPLETED
                    res.progress_pct = 100.0
                    if str(res.height) in result["resolutions"]:
                        rel = job_dir / f"{res.height}p"
                        res.output_path = str(rel)
                fresh.status = JobStatus.COMPLETED
                fresh.progress_pct = 100.0
                fresh.error = None

                # Record concrete output files for the completed resolutions.
                from .models import OutputFile
                for res in fresh.resolutions:
                    res_dir = job_dir / f"{res.height}p"
                    if res_dir.exists():
                        rel = res_dir.relative_to(job_dir)
                        for path in res_dir.iterdir():
                            if path.is_file():
                                osize = path.stat().st_size
                                kind = "hls" if path.suffix in (".m3u8", ".ts") else "mp4"
                                session.add(
                                    OutputFile(
                                        job_id=job_id,
                                        resolution_id=res.id,
                                        kind=kind,
                                        filename=str(rel / path.name),
                                        size_bytes=osize,
                                    )
                                )
                if result.get("thumbnail"):
                    session.add(
                        OutputFile(
                            job_id=job_id,
                            kind="thumbnail",
                            filename=result["thumbnail"],
                            size_bytes=(job_dir / result["thumbnail"]).stat().st_size,
                        )
                    )
            self._publish_job(session, job_id)

        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - report any worker failure
            logger.exception("job %s failed", job_id)
            self._mark_failed(session, job_id, f"{type(exc).__name__}: {exc}")
        finally:
            session.close()

    def _mark_failed(self, session, job_id: str, message: str) -> None:
        retry = False
        with session.begin():
            job = models.get_job(session, job_id)
            if job is None:
                return
            if (job.attempts or 0) >= self.max_retries:
                job.status = JobStatus.FAILED
                job.error = message
            else:
                # Transient failure: back to queued for a retry.
                job.status = JobStatus.QUEUED
                job.error = message
                retry = True
        self._publish_job(session, job_id)
        if retry:
            self.enqueue(job_id)  # re-enqueue for a retry round.

    # ------------------------------------------------------------------ #
    # Publish helpers
    # ------------------------------------------------------------------ #

    def _publish_progress(self, session, job_id: str, pct: float) -> None:
        self.publish(
            {
                "type": "progress",
                "job_id": job_id,
                "progress_pct": round(pct, 1),
            }
        )

    def _publish_job(self, session, job_id: str) -> dict:
        job = models.get_job(session, job_id)
        data = job.to_dict() if job else {"id": job_id, "status": "unknown"}
        data["type"] = "job"
        self.publish(data)
        return data


def run_sync(coro: Awaitable):
    """Run a coroutine to completion from a non-async thread (CLI/tests)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
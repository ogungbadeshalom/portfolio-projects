# Distributed Task Scheduler

## Project Title
Distributed Task Scheduler (Python + Redis)

## Goal
A production-grade distributed task scheduler: schedule tasks for future execution, distribute across multiple workers, retry with exponential backoff, dead-letter queue for permanent failures, observability.

## Why this project
Reliability engineering at its core. Teaches: idempotency, retry strategies, distributed locking, dead-letter queues, observability, failure handling.

## What You Build
A scheduler + worker system:

```bash
scheduler schedule "send_email" --at "2026-07-15T10:00:00" --payload '{"to":"user@example.com"}'
scheduler schedule "cleanup" --cron "0 * * * *" --payload '{}'
scheduler list                       # list all tasks
scheduler show TASK_ID              # task details + history
scheduler cancel TASK_ID
scheduler retry TASK_ID
scheduler dlq                       # show dead letter queue
```

Web UI at `http://localhost:9000/`:
- Task list with status (pending, running, done, failed, dead)
- Worker status (active, idle)
- DLQ review with retry/skip buttons
- Task timeline view
- Metrics dashboard (tasks/min, success rate, avg latency)

## Tech
- **Python 3.11+**
- **Redis** (queue, locks, streams)
- **Celery** (task framework) OR custom Redis-based
- **APScheduler** (cron-style scheduling)
- **FastAPI** (admin UI + API)
- **prometheus_client** (metrics)
- **structlog** (structured logging)

## Architecture

```
scheduler/
├── scheduler/
│   ├── __init__.py
│   ├── main.py             # FastAPI entry (admin UI)
│   ├── cli.py              # Click CLI
│   ├── models.py           # Task, TaskRun, Worker
│   ├── queue.py            # Redis-based task queue (RPOPLPUSH for safety)
│   ├── scheduler.py        # APScheduler for cron/one-time tasks
│   ├── worker.py           # Worker loop, executes tasks
│   ├── retry.py            # Exponential backoff logic
│   ├── dlq.py              # Dead letter queue management
│   ├── registry.py         # Task function registry (decorator-based)
│   ├── metrics.py          # Prometheus metrics
│   ├── routes/
│   │   ├── tasks.py
│   │   ├── workers.py
│   │   └── metrics.py
│   ├── templates/
│   │   ├── dashboard.html
│   │   ├── tasks.html
│   │   └── task_detail.html
│   └── config.py
├── tests/
└── CLAUDE.md
```

## Build Order

1. **`models.py`** — Task (id, name, payload_json, scheduled_at, status, attempts, max_attempts, last_error, created_at, completed_at), TaskRun (id, task_id, started_at, ended_at, status, error, worker_id), Worker (id, hostname, last_heartbeat, status)
2. **`registry.py`** — `@task(name="send_email")` decorator registers functions, returns TaskFunc with metadata
3. **`queue.py`** — Redis-based queue: `enqueue(task)`, `dequeue(worker_id)` (uses RPOPLPUSH for safety), `ack(task_id)`, `nack(task_id, error)`
4. **`scheduler.py`** — APScheduler scans for due tasks every 10s, enqueues them
5. **`worker.py`** — Worker loop: dequeue → lookup function → execute → ack/nack
6. **`retry.py`** — exponential backoff: `next_attempt_at = now + (2 ** attempts) * base_delay_seconds`, with jitter
7. **`dlq.py`** — tasks exceeding max_attempts move to DLQ, can be retried manually
8. **`metrics.py`** — Prometheus counters: tasks_total{status}, task_duration_seconds, dlq_size
9. **`routes/`** — admin API for tasks, workers, metrics
10. **Templates** — dashboard, task list, task detail

## Requirements

- Multiple workers can run in parallel (distributed)
- Tasks survive worker crashes (Redis persistence)
- Idempotent task execution (tasks can be retried safely)
- Exponential backoff with jitter on failures
- Dead letter queue after N attempts (default: 5)
- One-time and cron-scheduled tasks
- Task timeout (kill long-running tasks, default 5 min)
- Worker heartbeat (detect dead workers)
- Prometheus metrics endpoint (`/metrics`)
- Web UI for DLQ review (retry, skip, view error)
- Task dependencies (run Task B after Task A succeeds)
- Rate limiting per task name (max N per minute)

## Code Standards

- All Redis ops use `redis.asyncio` (async)
- Tasks are JSON-serializable (no complex objects in payload)
- Worker uses Redis BRPOPLPUSH for blocking wait (no busy polling)
- Task acknowledgment MUST happen before next poll (at-least-once delivery)
- Idempotency keys: tasks can specify `idempotency_key`, deduplicated on enqueue
- All task executions wrapped in try/except, exceptions captured, retried
- Long-running tasks get cancelled after timeout (asyncio.CancelledError)
- Worker gracefully shuts down on SIGTERM (finishes current task)
- Structured logging with task_id and worker_id context

## Verification

```bash
# Start Redis
docker run -d -p 6379:6379 redis:7-alpine

# Start 2 workers
python -m scheduler.worker --id worker-1 &
python -m scheduler.worker --id worker-2 &

# Schedule tasks
scheduler schedule "send_email" --at "2026-07-15T10:00:00" --payload '{"to":"test@example.com"}'
scheduler schedule "cleanup" --cron "*/5 * * * *" --payload '{}'

# List
scheduler list

# Open dashboard
open http://localhost:9000/

# Trigger a failing task (test DLQ)
scheduler schedule "fail_task" --at "now"

# Check DLQ
scheduler dlq

# Metrics
curl http://localhost:9000/metrics

# Run tests
pytest tests/ -v
```

## Stretch Goals

- Task priorities (high/normal/low queue)
- Task rate limiting (max N per minute per task name)
- Distributed locks (prevent two workers running same task)
- Workflow engine (DAG of tasks)
- Cron syntax extension (e.g., "every 5 minutes", "every Monday at 9am")
- Failed task auto-replay after N hours
- Per-tenant task isolation
- S3 archival of completed task results
- Webhook on task lifecycle (notify external systems)

## What You'll Learn

- Distributed task queue patterns
- Redis as queue + lock + state store
- Exponential backoff with jitter
- Dead letter queue patterns
- Idempotency in distributed systems
- Worker heartbeat + dead worker detection
- Prometheus metrics
- APScheduler for cron-style scheduling
- At-least-once vs at-most-once delivery

## Time Estimate
16-20 hours for MVP. 30-40 hours with workflows + dependencies + observability + admin UI + tests.
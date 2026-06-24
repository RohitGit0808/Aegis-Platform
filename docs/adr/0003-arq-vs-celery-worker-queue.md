# ADR 0003 — arq vs Celery for the worker queue

## Status

Accepted

## Context

Triggering a run and executing it must be decoupled: `POST /suites/{id}/runs`
returns `202 Accepted` immediately, and the actual execution (`execute_run`)
happens out of band so it can scale independently and not block the request.

The execution path is **fully `async`** — it opens its own async SQLAlchemy
session, awaits the async cache for pub/sub, and awaits the async healing engine
(including async LLM calls). Whatever queue we choose must run async task
functions natively, on the same event-loop model as the rest of the platform.

We also have the recurring zero-infrastructure constraint: local dev, CI and
demos must run with **no Redis and no separate worker process**, while production
uses a horizontally-scalable worker pool.

## Decision

Use **arq** (async Redis queue) for out-of-process execution, behind a
`RunDispatcher` protocol with two interchangeable backends selected automatically
from configuration (`aegis.workers.dispatch.get_dispatcher`):

- **`ArqDispatcher`** (when `AEGIS_REDIS_URL` is set): enqueues an
  `execute_run_task` job onto Redis; a pool of arq workers
  (`arq aegis.workers.arq_worker.WorkerSettings`, `max_jobs =
  AEGIS_WORKER_CONCURRENCY`) consumes it. This is the production path.
- **`InlineDispatcher`** (when no Redis URL — `settings.use_fake_cache`): runs
  `execute_run` as an in-process `asyncio.create_task`, holding a strong
  reference so the task isn't garbage-collected mid-flight. Zero infrastructure.

The API only ever calls `get_dispatcher().enqueue(run.id)` **after committing**
the run row, so the worker can never race an uncommitted row. The dispatcher is
chosen once and cached; calling code is identical regardless of backend.

## Consequences

**Positive**
- arq's task functions are `async`-native, so `execute_run` runs unchanged on the
  same event-loop model — no sync/async bridging, no thread pool for I/O-bound work.
- arq is lightweight: Redis-only (which we already run for cache/rate-limit/
  pub/sub), no extra broker/result-backend to operate.
- The `InlineDispatcher` fallback makes the whole platform runnable and testable
  with zero infra and gives fast, deterministic tests (no queue round-trip).
- Worker capacity scales independently of the API tier — add worker pods to drain
  a backlog without touching API replicas.
- Re-delivery is safe: `execute_run` no-ops unless the run is still `QUEUED`.

**Negative / trade-offs**
- arq has a smaller ecosystem and fewer integrations/operational tooling than
  Celery (less third-party monitoring, fewer Stack Overflow answers).
- Fewer built-in features (e.g. complex routing, beat-style scheduling, rich
  result backends) — acceptable for this workload, which is a single task type.
- Two execution paths (inline vs arq) must be kept behaviourally equivalent;
  the shared `execute_run` body mitigates this since both invoke the same code.
- Hard dependency on Redis for the production path (already a given here).

## Alternatives considered

- **Celery** — the most popular Python task queue, mature and feature-rich, but
  historically **sync-first**; running our async `execute_run` would require an
  event-loop bridge or rewriting the executor to sync (and then re-bridging the
  async DB/cache/LLM clients). Heavier operationally (broker + result backend).
  Rejected for impedance mismatch with an all-async codebase.
- **RQ (Redis Queue)** — simple and Redis-based, but sync-only; same async
  mismatch as Celery.
- **Dramatiq** — capable, but its async support is secondary and it adds another
  dependency without a decisive advantage over arq for this use case.
- **Cloud-native queues (SQS / Cloud Tasks / Pub/Sub)** — would couple the
  platform to a specific cloud and break the zero-infra local story; arq + the
  inline fallback keeps the platform portable and self-contained.
- **In-process only (no queue)** — fine for dev (and is exactly the inline
  fallback), but cannot scale execution independently of the API in production.

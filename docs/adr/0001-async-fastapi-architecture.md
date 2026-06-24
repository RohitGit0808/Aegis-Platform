# ADR 0001 — Async FastAPI architecture

## Status

Accepted

## Context

Aegis orchestrates test runs that are dominated by I/O: database reads/writes,
Redis queue and pub/sub traffic, and outbound LLM calls to Anthropic for locator
healing. A single run touches all three, and the platform must stream live
progress to connected UIs over WebSockets while serving normal CRUD traffic.

The workload is therefore high-concurrency and I/O-bound rather than CPU-bound.
We also imposed a hard product constraint: the platform must run end-to-end with
**zero external infrastructure** (SQLite + an in-process cache) for local dev,
CI and demos, and scale to Postgres + Redis + a worker pool in production without
changing calling code. We needed:

- A web framework with first-class `async`/`await` so thousands of in-flight I/O
  operations don't each cost a thread.
- Native WebSocket support for the live run feed.
- Strong request/response validation and an OpenAPI contract for the front-end
  and external integrators.
- An async-capable ORM so DB access doesn't block the event loop.

## Decision

Build the service on **FastAPI (async) running on uvicorn/ASGI**, with:

- **SQLAlchemy 2.0 async** (typed `mapped_column`) + **Alembic** for migrations,
  via an `async_sessionmaker`. SQLite (`aiosqlite`) locally, Postgres (`asyncpg`)
  in production — selected purely by `AEGIS_DATABASE_URL`.
- **Pydantic v2** DTOs as the wire contract, decoupled from ORM models
  (`from_attributes` for serialisation), plus **pydantic-settings** for 12-factor
  configuration.
- A **layered / hexagonal** structure: inbound adapters (routers, WS, CLI) →
  application services → domain core → outbound adapters (repositories, cache,
  LLM, dispatch). Dependencies point inward; ports are Python `Protocol`s.
- A **uniform error envelope** produced by a single set of exception handlers
  mapping typed domain exceptions to HTTP — keeping the core HTTP-agnostic and
  reusable from the CLI and workers.
- **structlog** structured logging with correlation ids, **Prometheus** RED
  metrics, and opt-in **OpenTelemetry** tracing.

## Consequences

**Positive**
- High concurrency on a small footprint; I/O overlaps naturally on the event loop.
- The same async services are reusable from HTTP routes, the Typer CLI and the
  background workers, with no duplicated business logic.
- Auto-generated OpenAPI (`/docs`, `/redoc`) and rigorous validation reduce
  integration friction and class-of-bug.
- The DB/cache/dispatch seams let the platform boot with zero infra yet scale by
  flipping two env vars.

**Negative / trade-offs**
- Async is viral: every I/O path (repositories, cache, LLM, healing engine) must
  be `async`, and a stray blocking call can stall the event loop. CPU-heavy work
  must be pushed off the loop (here, run execution lives in workers).
- Async SQLAlchemy 2.0 has a steeper learning curve and stricter session/lifecycle
  rules than the sync ORM.
- Testing requires `pytest-asyncio` and ASGI lifespan management.

## Alternatives considered

- **Django + DRF** — mature and batteries-included, but historically sync-first;
  async support is partial and WebSockets need Channels. Heavier than needed for a
  service-oriented API.
- **Flask (sync) + Celery + gevent/threads** — would force thread-per-request
  concurrency for an I/O-bound workload and bolt-on WebSocket/OpenAPI support.
- **Starlette alone** — FastAPI *is* Starlette plus the dependency-injection,
  validation and OpenAPI layer we specifically wanted; using raw Starlette would
  mean re-implementing those.
- **Node.js/Go** — strong async stories, but Python is mandated by the LLM/test
  ecosystem (Anthropic SDK, Playwright/Selenium affinity) and team skill set.

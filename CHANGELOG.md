# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_Nothing yet._

## [1.0.0] — 2026-06-24

Initial public release of **Aegis** — a distributed, AI-powered self-healing
test-orchestration platform.

### Added

- **Async FastAPI service** (ASGI/uvicorn) with an application factory, lifespan
  management, CORS, a uniform error envelope (`{"error": {"code", "message",
  "details"}}`), and OpenAPI docs at `/docs` and `/redoc`.
- **Authentication & RBAC**: register / login (OAuth2 password flow) / refresh /
  `me` endpoints; Argon2id password hashing; JWT access and refresh tokens (HS256)
  with a verified `type` claim; roles `admin`, `engineer`, `viewer` enforced via
  `require_roles` (admins always pass).
- **Suite & case management**: full CRUD for test suites and inline/standalone
  test cases; slug-uniqueness enforcement; ordered, JSON-stored steps validated
  against a `StepSpec` schema.
- **Test runs**: trigger (`202 Accepted`), list (with `suite_id` filter), fetch
  with step results, and cancel. Idempotent triggering via an optional
  `Idempotency-Key` header.
- **Self-healing engine**: heuristic-first matcher (weighted by `data-testid`,
  `id`, text, classes, tag, attributes) with an LLM fallback (Claude
  `claude-opus-4-8`, structured JSON output) and a hybrid merge when both agree.
  Auto-accept above `healing_min_confidence` (default 0.6); lower-confidence heals
  are flagged for human review. Degrades gracefully to heuristic-only when no
  API key is configured.
- **Healing review**: list healing events per run and accept/reject proposed
  locators.
- **Live run streaming**: WebSocket `runs/{run_id}/stream` relaying
  `run.started`, `step.completed`, and `run.finished` events over cache pub/sub.
- **Worker execution**: decoupled dispatch behind a `RunDispatcher` protocol with
  an out-of-process **arq** backend (production) and an in-process inline backend
  (zero-infra dev/test), selected automatically from configuration. Deterministic
  simulated step executor exercising the full DB/healing/metrics/events path.
- **Persistence**: SQLAlchemy 2.0 async ORM (typed `mapped_column`) with Alembic
  migrations; portable VARCHAR enums for SQLite/Postgres parity; cascading
  foreign keys. Entities: `User`, `TestSuite`, `TestCase`, `TestRun`,
  `StepResult`, `HealingEvent`.
- **Cache / queue / pub-sub** facade over `redis.asyncio` with a transparent
  in-process **FakeRedis** fallback; backs rate limiting, idempotency and run
  streaming.
- **Resilience primitives**: timeouts, tenacity retry-with-backoff, and a
  dependency-free async circuit breaker fronting the LLM provider.
- **Observability**: Prometheus RED metrics plus domain golden signals at
  `/metrics`; structlog structured logging with correlation ids (`X-Request-ID`);
  opt-in OpenTelemetry tracing for FastAPI and SQLAlchemy.
- **Rate limiting**: per-client fixed-window limiter (default 120 req / 60s).
- **Operational endpoints**: `/healthz` (liveness) and `/readyz` (readiness,
  checking DB and cache).
- **Admin CLI** (`aegis`): `version`, `serve`, `create-user`, and `seed`
  (creates `admin@aegis.dev` and a demo suite that passes, heals, and fails
  honestly).
- **Documentation**: architecture overview, operations runbook, API reference,
  and architecture decision records (ADR 0001–0003).

[Unreleased]: https://github.com/rohit-saxena/aegis-platform/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/rohit-saxena/aegis-platform/releases/tag/v1.0.0

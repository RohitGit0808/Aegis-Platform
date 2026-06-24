# Aegis — Operations Runbook

This runbook covers deploying, observing, and recovering the Aegis platform in
production. It assumes the production topology: a horizontally-scaled FastAPI
tier, a pool of arq workers, Postgres, and Redis.

---

## 1. Topology

```
        clients ──▶ load balancer ──▶ [ FastAPI API replicas (N) ]
                                            │            │
                                  enqueue   │            │  SQL
                                            ▼            ▼
                                        [ Redis ]    [ Postgres ]
                                            ▲            ▲
                                  consume   │            │  SQL
                                     [ arq worker pool (M) ]
```

- **API tier** — stateless; scale horizontally. Serves HTTP + WebSocket.
- **Worker tier** — runs `execute_run`; scale independently to drain backlog.
- **Redis** — queue, rate-limit counters, idempotency keys, run pub/sub.
- **Postgres** — system of record.

The same image serves both tiers; the worker tier just runs a different command.

---

## 2. Deploy

### Prerequisites
- Python 3.11+ image with the package installed (`pip install .` / wheel).
- Env configured (all `AEGIS_`-prefixed; see `.env.example`). **Production must set:**
  - `AEGIS_ENVIRONMENT=production`
  - `AEGIS_SECRET_KEY` — long random string
    (`python -c "import secrets; print(secrets.token_urlsafe(48))"`)
  - `AEGIS_DATABASE_URL=postgresql+asyncpg://USER:PASS@HOST:5432/aegis`
  - `AEGIS_REDIS_URL=redis://HOST:6379/0` (enables arq + real cache)
  - `AEGIS_ANTHROPIC_API_KEY` — to enable LLM healing (optional; heuristic-only
    without it)
  - `AEGIS_CORS_ORIGINS` — your front-end origin(s)

> In `production`, the app does **not** auto-create the schema. Apply migrations
> first (see step 1).

### Steps
1. **Migrate the database** (out of band, before rolling new code):
   ```bash
   alembic upgrade head
   ```
2. **Start the API tier**:
   ```bash
   aegis serve --host 0.0.0.0 --port 8000
   # or: uvicorn aegis.main:app --host 0.0.0.0 --port 8000 --workers 4
   ```
3. **Start the worker tier** (only when `AEGIS_REDIS_URL` is set):
   ```bash
   arq aegis.workers.arq_worker.WorkerSettings
   ```
   Worker concurrency = `AEGIS_WORKER_CONCURRENCY` (default 8) per process.
4. **Seed a first admin** (one-off, if needed):
   ```bash
   aegis create-user admin@yourco.com '<password>' --role admin
   # demo data: aegis seed  (creates admin@aegis.dev / aegis-admin-pw + 'aegis-demo' suite)
   ```
5. **Verify** with the probes below before shifting traffic.

> If `AEGIS_REDIS_URL` is empty, the platform runs in single-process mode:
> FakeRedis cache + `InlineDispatcher` (runs execute in-process). No worker tier
> is needed — but this is for dev/demo only, not production.

---

## 3. Health & readiness probes

| Probe | Endpoint | Healthy | Use for |
|-------|----------|---------|---------|
| **Liveness** | `GET /healthz` | `200 {"status":"alive"}` | Restart a wedged process. Cheap; no dependency checks. |
| **Readiness** | `GET /readyz` | `200 {"ready":true,…}` | Gate LB traffic. Checks DB (`SELECT 1`) **and** cache (`ping`); `503` if either is down. |
| **Info** | `GET /api/v1/health` | `200` with version/env | Confirm the deployed version. |

Recommended Kubernetes settings: liveness on `/healthz` (failureThreshold ~3),
readiness on `/readyz` (so a pod with a broken DB/cache connection is pulled from
rotation but not killed).

---

## 4. Key metrics & alerts

Scrape `GET /metrics` (Prometheus). Golden signals:

| Metric | Type | Watch for |
|--------|------|-----------|
| `aegis_http_requests_total{status}` | counter | 5xx rate spike → error budget burn. |
| `aegis_http_request_duration_seconds` | histogram | p95/p99 latency regression. |
| `aegis_active_runs` | gauge | Stuck high → workers wedged or backlog. |
| `aegis_runs_total{status}` | counter | Rising `error`/`failed` ratio. |
| `aegis_run_duration_seconds` | histogram | Run latency regression. |
| `aegis_worker_tasks_total{task,outcome}` | counter | `outcome="error"` climbing. |
| `aegis_healing_attempts_total{strategy,outcome}` | counter | `outcome="no_match"` or `low_confidence` spiking → DOMs changed or LLM degraded. |
| `aegis_healing_confidence` | histogram | Drop in mean confidence → review backlog risk. |

**Suggested alerts:**
- HTTP 5xx ratio > 2% for 5m (page).
- `/readyz` failing on any replica for 2m (page).
- `aegis_active_runs` flat/non-zero with no `aegis_runs_total` increase for 15m →
  workers stalled (page).
- Queue backlog (Redis list length for the arq queue) growing for 10m (ticket).
- `circuit.open` log event for `claude-healing` (info → ticket if sustained).

Correlate incidents using the structured logs — every line carries the request's
correlation id (set via / returned in `X-Request-ID`). Set `AEGIS_LOG_JSON=true`
in production for machine-ingestible logs.

---

## 5. Common incidents

### 5.1 Worker backlog / runs stuck in `queued`
**Symptoms**: new runs stay `queued`; `aegis_active_runs` low while queue length
grows; `step.completed` events stop arriving on the WS feed.

**Diagnose**:
- Are worker processes alive? (`arq` healthcheck / pod status.)
- Redis reachable from workers? (`AEGIS_REDIS_URL` correct, network ok.)
- Any `worker.startup` log on the worker tier? `aegis_worker_tasks_total` increasing?

**Resolve**:
- Scale out the worker tier (more pods / processes) to drain.
- Raise `AEGIS_WORKER_CONCURRENCY` (CPU/DB-pool permitting) and roll workers.
- A queued run is safe to re-deliver — `execute_run` no-ops unless the run is
  still `QUEUED`, so duplicates can't double-execute.

### 5.2 Database down / unreachable
**Symptoms**: `/readyz` returns `503` with `checks.database=false`; writes 500;
`aegis_http_requests_total{status="500"}` spikes.

**Diagnose**: connectivity, credentials, connection-pool exhaustion
(`pool_size` + `max_overflow`), failover in progress.

**Resolve**:
- `/readyz` automatically pulls affected API pods from the LB — leave them up
  (liveness still passes) so they recover when the DB returns.
- Fail over / restart Postgres. `pool_pre_ping=True` discards dead connections
  on checkout, so recovery is automatic once the DB is back.
- If pool-exhausted under load, raise `AEGIS_DB_POOL_SIZE` / `AEGIS_DB_MAX_OVERFLOW`
  and roll, or scale the API tier down to reduce total connections.

### 5.3 Redis down / unreachable
**Symptoms**: `/readyz` `checks.cache=false`; new runs can't be enqueued
(`ArqDispatcher`); rate limiting/idempotency/WS streaming impaired.

**Resolve**:
- Restore Redis (managed failover / Sentinel / restart). The cache facade
  reconnects lazily.
- Impact is contained: in-flight runs already executing continue against the DB;
  only enqueue, rate limiting, idempotency dedupe and live streaming depend on
  Redis. `GET /runs/{id}` remains the source of truth.
- Do **not** "fix" prod by unsetting `AEGIS_REDIS_URL` — that silently switches to
  FakeRedis + in-process execution and loses the worker tier.

### 5.4 LLM provider failure → heuristic fallback / circuit breaker
**Symptoms**: `healing.llm.failed` warnings; `circuit.open` for `claude-healing`;
`aegis_healing_attempts_total{strategy="llm"}` drops; more `low_confidence`
outcomes.

**Behaviour (by design — usually no action needed)**:
- Each Claude call is wrapped in a 20s timeout (`healing_llm_timeout_seconds`)
  and a circuit breaker (`failure_threshold=4`, `reset_timeout=30s`).
- On any failure (timeout, refusal, parse error, open circuit) the engine logs a
  warning and **falls back to the heuristic proposal** — healing keeps working,
  just without the LLM's extra recall.
- The breaker half-opens after 30s and recovers automatically when the provider
  returns.

**If sustained**: check the Anthropic status/API key/quota. As a deliberate
mitigation you may disable the LLM path entirely with `AEGIS_HEALING_ENABLED=false`
(or unset `AEGIS_ANTHROPIC_API_KEY`) and roll — the platform becomes heuristic-only
with no code change.

### 5.5 Rate-limit false positives
**Symptoms**: legitimate clients get `429 rate_limited`.

**Resolve**: raise `AEGIS_RATE_LIMIT_REQUESTS` / `AEGIS_RATE_LIMIT_WINDOW_SECONDS`,
or set `AEGIS_RATE_LIMIT_ENABLED=false` temporarily. Note the limiter keys on
client IP — behind a proxy, ensure the real client IP reaches the app.

---

## 6. Scaling

- **API tier**: stateless — add replicas behind the LB. CPU/latency bound.
- **Worker tier**: scale pods to match run throughput; tune
  `AEGIS_WORKER_CONCURRENCY` per pod. Watch DB pool headroom as you scale workers
  (each concurrent run opens its own session).
- **Postgres**: vertical scale + read replicas; ensure pool sizing
  (`AEGIS_DB_POOL_SIZE`, `AEGIS_DB_MAX_OVERFLOW`) accounts for `API_replicas ×
  pool + workers × concurrency`.
- **Redis**: replication / Sentinel or managed cluster for HA.

---

## 7. Rollback

1. **Code**: redeploy the previous image/tag to the API and worker tiers. The app
   is stateless — a rollback is a re-roll.
2. **Schema**: roll back the offending migration explicitly **after** code is
   reverted to a compatible version:
   ```bash
   alembic downgrade -1        # or: alembic downgrade <revision>
   ```
   Prefer backward-compatible (expand/contract) migrations so code can roll back
   without an immediate schema downgrade.
3. **Verify** `/readyz` and `GET /api/v1/health` (version) on every tier before
   restoring full traffic.
4. **In-flight runs**: a rollback may interrupt running executions. Affected runs
   can be re-triggered; queued runs are picked up by whichever worker version is
   live (executor no-ops unless `QUEUED`).

---

## 8. Backups

- **Postgres** is the system of record — schedule regular automated backups
  (managed snapshots + PITR/WAL archiving). Test restores periodically. Retention
  per your data policy.
- **Redis** holds only ephemeral/derived state (queue jobs, rate-limit counters,
  idempotency keys, transient pub/sub). It does **not** require backup for
  correctness — on loss, queued-but-unstarted runs may need re-triggering, and
  idempotency dedupe windows reset. Persistence (AOF/RDB) is still recommended to
  avoid losing queued jobs on restart.
- **Secrets** (`AEGIS_SECRET_KEY`, `AEGIS_ANTHROPIC_API_KEY`): store in a secrets
  manager; rotating `AEGIS_SECRET_KEY` invalidates all issued JWTs (forces
  re-login) — plan rotations accordingly.

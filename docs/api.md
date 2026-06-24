# Aegis — API Reference

Base URL: all application endpoints are under the v1 prefix **`/api/v1`**
(`AEGIS_API_V1_PREFIX`). Interactive docs: `GET /docs` (Swagger) and `GET /redoc`.

- **Auth**: Bearer JWT in `Authorization: Bearer <access_token>`, except
  `auth/register`, `auth/login`, `auth/refresh` (public) and the WebSocket route
  (uses a `?token=` query param).
- **Roles**: `admin`, `engineer`, `viewer`. Write endpoints require `engineer`;
  **`admin` always passes** any role check. Read endpoints require only a valid
  token.
- **Content type**: `application/json` for request/response bodies, except
  `auth/login`, which is an OAuth2 password form (`application/x-www-form-urlencoded`).

---

## Error envelope

Every error — domain, validation, or unexpected — uses one shape so clients can
branch on the stable, machine-readable `code` instead of parsing prose:

```json
{
  "error": {
    "code": "not_found",
    "message": "The requested resource was not found.",
    "details": {}
  }
}
```

| HTTP | `code` | Raised when |
|------|--------|-------------|
| 401 | `unauthorized` / `invalid_credentials` / `invalid_token` / `token_expired` / `token_invalid` / `token_wrong_type` | Missing/invalid/expired token, or bad login. |
| 403 | `forbidden` / `insufficient_role` | Authenticated but lacks the required role, or disabled account. |
| 404 | `not_found` | Suite, run, or healing event does not exist. |
| 409 | `conflict` / `email_taken` / `slug_taken` / `idempotency_conflict` | Uniqueness violation or idempotency-key reuse with a different request. |
| 422 | `validation_error` | Request body/query failed validation. `details.errors` carries the field-level list. |
| 429 | `rate_limited` | Per-client rate limit exceeded. |
| 502 | `healing_failed` | The self-healing engine could not produce a usable locator. |
| 503 | `service_unavailable` / `timeout` / `circuit_open` | A downstream dependency is unavailable or timed out. |
| 500 | `internal_error` | Unhandled error (no stack trace leaked to the client). |

---

## Pagination

List endpoints accept `page` (1-based, `>= 1`, default `1`) and `size`
(`1`–`100`, default `20`) as query params and return a typed envelope:

```json
{
  "items": [ /* … */ ],
  "total": 137,
  "page": 1,
  "size": 20,
  "pages": 7
}
```

`pages = ceil(total / size)`. Sizes above `100` (`MAX_SIZE`) are rejected by
query validation (`422`).

---

## Authentication

### `POST /auth/register`
Public. Create a user account.

- **Body** (`UserCreate`): `email`, `full_name` (1–255), `password` (8–128),
  `role` (`admin`|`engineer`|`viewer`, default `engineer`).
- **Response** `201` (`UserRead`): `id, email, full_name, role, is_active, created_at`.
- **Errors**: `409 email_taken`, `422 validation_error`.

### `POST /auth/login`
Public. OAuth2 password flow — **form-encoded**, not JSON.

- **Body** (form): `username` (the email), `password`.
- **Response** `200` (`Token`): `access_token, refresh_token, token_type="bearer", expires_in`.
- **Errors**: `401 invalid_credentials`, `403 forbidden` (disabled account).

### `POST /auth/refresh`
Public. Exchange a refresh token for a fresh token pair.

- **Body**: `{ "refresh_token": "<jwt>" }`.
- **Response** `200` (`Token`).
- **Errors**: `401` (`token_expired` / `token_invalid` / `token_wrong_type` / `invalid_token`).

### `GET /auth/me`
Auth required (any role). Return the current user.

- **Response** `200` (`UserRead`).
- **Errors**: `401`.

---

## Suites & cases

### `POST /suites`
Role: **engineer**. Create a suite (optionally with inline cases).

- **Body** (`SuiteCreate`): `name`, `slug` (`^[a-z0-9][a-z0-9-]*$`),
  `description?`, `target_base_url`, `tags[]`, `cases[]` (each `TestCaseCreate`:
  `name`, `order_index`, `steps[]` where a `StepSpec` is
  `{action, selector?, value?, expected?}`).
- **Response** `201` (`SuiteDetail` — `SuiteRead` + `cases[]`).
- **Errors**: `409 slug_taken`, `422`, `403 insufficient_role`.

### `GET /suites`
Auth required. Paginated list of suites (newest first).

- **Query**: `page`, `size`.
- **Response** `200` (`Page[SuiteRead]`).

### `GET /suites/{suite_id}`
Auth required. Fetch one suite with its cases.

- **Response** `200` (`SuiteDetail`).
- **Errors**: `404 not_found`.

### `PATCH /suites/{suite_id}`
Role: **engineer**. Partial update.

- **Body** (`SuiteUpdate`, all optional): `name`, `description`,
  `target_base_url`, `tags`, `is_active`.
- **Response** `200` (`SuiteDetail`).
- **Errors**: `404`, `422`, `403`.

### `DELETE /suites/{suite_id}`
Role: **engineer**. Delete a suite (cascades to cases, runs, results, healing events).

- **Response** `204` (no body).
- **Errors**: `404`, `403`.

### `POST /suites/{suite_id}/cases`
Role: **engineer**. Append a case to a suite.

- **Body** (`TestCaseCreate`).
- **Response** `201` (`TestCaseRead`): `id, suite_id, name, order_index, is_active, steps[]`.
- **Errors**: `404`, `422`, `403`.

---

## Runs

### `POST /suites/{suite_id}/runs`
Role: **engineer**. Trigger a run; execution is asynchronous.

- **Headers** (optional): `Idempotency-Key: <string>` — replaying the same key
  returns the original run instead of creating a new one.
- **Body** (`RunCreate`): `trigger` (`manual`|`scheduled`|`ci`|`webhook`,
  default `manual`).
- **Response** `202 Accepted` (`RunRead`): `id, suite_id, status, trigger,
  total_cases, passed_count, failed_count, healed_count, duration_ms?, error?,
  started_at?, finished_at?, created_at`. A freshly-created run comes back as
  `status: "queued"`.
- **Errors**: `404 not_found` (suite), `403`, `422`.

### `GET /runs`
Auth required. Paginated list of runs (newest first).

- **Query**: `page`, `size`, `suite_id?` (filter).
- **Response** `200` (`Page[RunRead]`).

### `GET /runs/{run_id}`
Auth required. Fetch a run with its step results.

- **Response** `200` (`RunDetail` — `RunRead` + `results[]`, each `StepResultRead`:
  `id, case_name, step_index, action, status, original_selector?, healed_selector?,
  message?, duration_ms`).
- **Errors**: `404 not_found`.

### `POST /runs/{run_id}/cancel`
Role: **engineer**. Cancel a run if it is not already terminal.

- **Response** `200` (`RunRead`). A terminal run is returned unchanged.
- **Errors**: `404`, `403`.

---

## Healing

### `GET /runs/{run_id}/healing`
Auth required. List all healing events for a run.

- **Response** `200` (`list[HealingEventRead]`): each `id, run_id,
  original_selector, healed_selector?, strategy (none|heuristic|llm|hybrid),
  confidence, rationale?, succeeded, accepted (null=pending), created_at`.

### `POST /healing/{event_id}/review`
Role: **engineer**. Accept or reject a proposed locator (human review).

- **Body** (`HealingReviewRequest`): `{ "accepted": true }`.
- **Response** `200` (`HealingEventRead`, with `accepted` set).
- **Errors**: `404 not_found`, `403`.

---

## WebSocket — live run feed

### `WS /api/v1/runs/{run_id}/stream?token=<access_token>`

Streams run/step events in real time. The server subscribes to the cache pub/sub
channel `run:{run_id}` (the executor publishes to it) and relays each message as a
**text frame containing a JSON object**.

- **Auth**: pass an `access` JWT as the `token` query param. Required in
  production; optional otherwise. On failure the server closes with code `1008`
  (policy violation) before accepting.
- **Not rate-limited** (the limiter needs an HTTP request, which a WS lacks).
- **Direction**: server → client only; the client does not send application
  messages.

Every frame has an `event` discriminator plus event-specific fields:

**`run.started`** — emitted once when the run transitions to RUNNING:
```json
{ "event": "run.started", "run_id": "<uuid>", "suite": "<suite-slug>" }
```

**`step.completed`** — emitted after each step is recorded:
```json
{
  "event": "step.completed",
  "case": "Authentication",
  "step_index": 3,
  "status": "healed",
  "healed_selector": "[data-testid=\"submit\"]"
}
```
`status` is one of `passed | failed | healed | skipped`. `healed_selector` is
`null` unless the step was healed.

**`run.finished`** — emitted once on completion (always, even on error):
```json
{
  "event": "run.finished",
  "status": "passed",
  "passed": 5,
  "failed": 0,
  "healed": 2,
  "duration_ms": 132
}
```
`status` is the terminal `RunStatus` (`passed | failed | error | cancelled`).

> Note: pub/sub delivery is best-effort — a publish failure never aborts the run,
> so a client may occasionally miss a frame. Treat the WS feed as a live
> convenience and `GET /runs/{id}` as the source of truth.

---

## Infrastructure endpoints (root app, no prefix)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/` | none | Service identity (`name`, `version`, `docs`). |
| GET | `/healthz` | none | Liveness probe → `{"status":"alive"}`. |
| GET | `/readyz` | none | Readiness probe; checks DB + cache. `200` ready, `503` not (`{"ready":bool,"checks":{"database":bool,"cache":bool}}`). |
| GET | `/metrics` | none | Prometheus exposition (`404` if `metrics_enabled=false`). |
| GET | `/api/v1/health` | rate-limited | Service metadata (`status, app, version, environment`). |
| GET | `/docs`, `/redoc` | none | OpenAPI UIs. |

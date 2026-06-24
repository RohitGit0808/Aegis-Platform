# Contributing to Aegis

Thanks for contributing! Aegis aims for a FANG-quality bar: clean, typed,
well-tested, idiomatic Python. This guide covers local setup, the quality gates,
and the contribution workflow.

---

## Development setup

**Requirements**: Python 3.11+ (3.12/3.13 supported). The platform runs with
**zero external infrastructure** by default (SQLite + an in-process FakeRedis +
in-process run execution), so no Docker, Postgres or Redis is needed to start.

```bash
# 1. Create and activate a virtualenv
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1

# 2. Install the package in editable mode with all dev extras
pip install -e ".[dev]"

# 3. Configure (optional — defaults work out of the box)
cp .env.example .env

# 4. Seed a demo admin + suite that exercises healing
aegis seed                       # admin@aegis.dev / aegis-admin-pw, suite 'aegis-demo'

# 5. Run the API
aegis serve --reload             # http://localhost:8000/docs
```

All configuration is environment-driven with the `AEGIS_` prefix
(`src/aegis/core/config.py`); see `.env.example` for the annotated list. Useful
toggles:

- `AEGIS_REDIS_URL` — set it to use real Redis + the out-of-process arq worker
  (otherwise FakeRedis + in-process execution).
- `AEGIS_ANTHROPIC_API_KEY` — set it to enable LLM-assisted healing (otherwise
  heuristic-only).

To exercise the production worker path locally:

```bash
export AEGIS_REDIS_URL=redis://localhost:6379/0
aegis serve
# in another shell:
arq aegis.workers.arq_worker.WorkerSettings
```

---

## Quality gates

Every change must pass lint, type-check and tests before review. The exact
configuration lives in `pyproject.toml`.

### Tests (pytest + pytest-asyncio)

```bash
pytest                           # full suite with coverage
pytest -m unit                   # fast, isolated tests (no I/O)
pytest -m integration            # API/db stack tests
pytest tests/path::test_name     # a single test
```

- `asyncio_mode = "auto"` — `async def` tests need no decorator.
- Coverage is enforced at **`fail_under = 80`** (branch coverage on `src/aegis`).
- Use the markers `@pytest.mark.unit` / `@pytest.mark.integration`.

### Lint (ruff)

```bash
ruff check .                     # lint
ruff format .                    # format (line length 100)
ruff check . --fix               # autofix where safe
```

Enabled rule sets: `E, F, I, N, UP, B, A, C4, SIM, PTH, RUF, ASYNC, S`
(pycodestyle, pyflakes, isort, naming, pyupgrade, bugbear, builtins,
comprehensions, simplify, use-pathlib, ruff, async, bandit-security).

### Type-check (mypy, strict)

```bash
mypy src/aegis
```

mypy runs in **`strict`** mode with the Pydantic plugin and `warn_unused_ignores`.
Add precise type annotations; avoid `# type: ignore` unless unavoidable (and scope
it with an error code).

### Security (bandit) & pre-commit

```bash
bandit -r src/aegis
pre-commit install               # one-time; runs ruff/mypy/bandit on commit
pre-commit run --all-files
```

---

## Code style

- **Async everywhere** on I/O paths — repositories, services, cache, healing,
  workers. Never make a blocking call on the event loop.
- **Layering** (see `docs/architecture.md`): routers → services → domain core →
  repositories/adapters. Dependencies point inward. Keep HTTP concerns out of
  services; raise typed `AegisError` subclasses and let
  `aegis.api.errors` map them to the wire envelope.
- **DTOs vs ORM**: validate inbound requests with Pydantic `*Create`/`*Update`
  schemas; serialise responses from ORM via `*Read`/`*Detail`. Don't leak ORM
  models across the API boundary.
- **Comment intent, not mechanics** — explain *why* where it isn't obvious;
  consistent with the existing module docstrings.
- `from __future__ import annotations` at the top of every module.
- Follow existing patterns in neighbouring files rather than introducing new ones.

---

## Database migrations

Dev/test bootstrap the schema directly (`create_all` runs on startup for
`LOCAL`/`TEST`). **Staging and production use Alembic.** When you change a model
in `src/aegis/db/models.py`:

```bash
# Generate a revision from the model diff
alembic revision --autogenerate -m "describe the change"

# Review the generated migration — autogenerate is a draft, not gospel.
# Check it works on both SQLite and Postgres (enums are portable VARCHAR by design).

# Apply locally to verify
alembic upgrade head
# and that it reverses cleanly
alembic downgrade -1
```

Prefer **backward-compatible (expand/contract)** migrations so code can roll back
without an immediate schema downgrade. Commit the migration alongside the model
change in the same PR.

---

## Commit conventions (Conventional Commits)

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<optional scope>): <short imperative summary>

<optional body explaining what & why>

<optional footer, e.g. BREAKING CHANGE: …, Refs #123>
```

Common types: `feat`, `fix`, `docs`, `refactor`, `test`, `perf`, `chore`,
`build`, `ci`. Examples:

```
feat(healing): boost confidence when heuristic and LLM agree
fix(runs): no-op execute_run unless the run is still QUEUED
docs(adr): record arq-vs-celery decision
```

Keep commits focused and atomic; the summary drives the changelog.

---

## Branch & PR flow

1. Branch off `main`: `git checkout -b feat/<short-name>`.
2. Make focused commits following the convention above.
3. Run the full gate locally: `ruff check . && mypy src/aegis && pytest`.
4. Open a PR against `main` with a clear description (what, why, how verified).
   Link any related issues.
5. Ensure CI is green and address review feedback. Squash-merge is preferred to
   keep `main` history clean and changelog-friendly.
6. Update `CHANGELOG.md` (Unreleased section) for any user-facing change.

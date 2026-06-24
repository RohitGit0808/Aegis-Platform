"""Integration-test fixtures: a real Aegis app on SQLite + fakeredis.

The whole point of this suite is to exercise the *actual* application — its
FastAPI app, dependency graph, SQLAlchemy session, services and the in-process
self-healing worker — with **zero external services**. SQLite (aiosqlite) backs
persistence and an in-process FakeRedis stands in for Redis/arq.

Critical ordering note
----------------------
``aegis.core.config`` builds a single cached ``Settings`` instance *at import
time*, and ``aegis.db.session`` builds the engine + sessionmaker from that
instance, also at import time. Therefore the test environment must be configured
**before any aegis module is imported**. We do that at the very top of this file
(conftest is imported before the test modules and before the app), so by the time
anything under ``aegis`` is touched the process already sees the test settings.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

# --------------------------------------------------------------------------- #
# 1. Configure the environment BEFORE importing any aegis module.
#    (env_prefix is ``AEGIS_``; see aegis.core.config.Settings.)
# --------------------------------------------------------------------------- #
_DB_PATH = Path(tempfile.gettempdir()) / f"aegis_itest_{uuid.uuid4().hex}.db"

os.environ.setdefault("AEGIS_ENVIRONMENT", "test")
# Force the values we depend on (setdefault would not override a stray .env).
os.environ["AEGIS_ENVIRONMENT"] = "test"
# ``timeout`` is forwarded to sqlite3.connect: the inline run executor writes
# from a background task, so a brief busy-wait avoids "database is locked" when a
# test's setup truncates tables while a prior run is still flushing.
os.environ["AEGIS_DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB_PATH.as_posix()}?timeout=30"
os.environ["AEGIS_REDIS_URL"] = ""  # empty => in-process FakeRedis (use_fake_cache)
os.environ["AEGIS_RATE_LIMIT_ENABLED"] = "false"
os.environ["AEGIS_ANTHROPIC_API_KEY"] = ""  # heuristic-only healing, no network
os.environ["AEGIS_METRICS_ENABLED"] = "true"
os.environ["AEGIS_DB_ECHO"] = "false"

# --------------------------------------------------------------------------- #
# 2. Now it is safe to import third-party + aegis modules.
# --------------------------------------------------------------------------- #
import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from asgi_lifespan import LifespanManager  # noqa: E402

from aegis.db.base import Base  # noqa: E402
from aegis.db.session import create_all, engine  # noqa: E402
from aegis.main import create_app  # noqa: E402
from tests import factories  # noqa: E402

API = "/api/v1"


@pytest.fixture(scope="session", autouse=True)
def _cleanup_db_file() -> Iterator[None]:
    """Remove the temporary SQLite file once the whole session finishes."""
    yield
    try:
        _DB_PATH.unlink(missing_ok=True)
    except OSError:  # pragma: no cover - platform/file-lock dependent
        pass


@pytest_asyncio.fixture
async def app() -> AsyncIterator[object]:
    """A real FastAPI app whose lifespan runs ``create_all()`` against SQLite.

    Function-scoped on purpose: pytest-asyncio (auto mode) runs each test in its
    own event loop, and the module-level async engine in ``aegis.db.session``
    must operate on the *current* loop. Re-running the lifespan per test rebinds
    the engine's connection pool to that loop; ``create_all()`` is idempotent so
    re-entering it is harmless. We isolate state by truncating tables up front.
    """
    # Ensure the schema exists (first test) before truncating, then wipe rows so
    # every test starts from a clean, isolated database.
    await create_all()
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())

    application = create_app()
    async with LifespanManager(application):
        yield application
        # Drain any in-flight inline run tasks so a run started in this test does
        # not leak into the next one's event loop / hold a write lock on SQLite.
        from aegis.workers.dispatch import _background_tasks

        pending = list(_background_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


@pytest_asyncio.fixture
async def client(app: object) -> AsyncIterator[httpx.AsyncClient]:
    """An httpx client bound to the ASGI app (no sockets, no live server)."""
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# --------------------------------------------------------------------------- #
# Auth helpers
# --------------------------------------------------------------------------- #
async def _register_and_login(client: httpx.AsyncClient, payload: dict) -> tuple[dict, dict]:
    """Register a user then log in; return (user_json, token_json)."""
    reg = await client.post(f"{API}/auth/register", json=payload)
    assert reg.status_code == 201, reg.text
    login = await client.post(
        f"{API}/auth/login",
        data={"username": payload["email"], "password": payload["password"]},
    )
    assert login.status_code == 200, login.text
    return reg.json(), login.json()


@pytest_asyncio.fixture
async def engineer_token(client: httpx.AsyncClient) -> str:
    """Access token for a freshly-registered ENGINEER user."""
    _, tokens = await _register_and_login(client, factories.user_create())
    return tokens["access_token"]


@pytest_asyncio.fixture
async def auth_headers(engineer_token: str) -> dict[str, str]:
    """Authorization headers for an ENGINEER (the common authenticated case)."""
    return {"Authorization": f"Bearer {engineer_token}"}


@pytest_asyncio.fixture
async def viewer_headers(client: httpx.AsyncClient) -> dict[str, str]:
    """Authorization headers for a VIEWER (used to assert RBAC denials)."""
    payload = factories.user_create(
        email="viewer@example.com", full_name="Vera Viewer", role="viewer"
    )
    _, tokens = await _register_and_login(client, payload)
    return {"Authorization": f"Bearer {tokens['access_token']}"}

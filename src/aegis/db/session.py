"""Async SQLAlchemy engine and session management.

Exposes the engine, an ``async_sessionmaker``, a FastAPI-friendly
``get_session`` dependency, and schema lifecycle helpers. Pooling parameters are
applied only for server databases (Postgres); SQLite uses the default pool.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from aegis.core.config import settings
from aegis.db.base import Base


def _build_engine() -> AsyncEngine:
    kwargs: dict[str, object] = {"echo": settings.db_echo, "pool_pre_ping": True}
    if settings.database_url.startswith("sqlite"):
        # Let concurrent writers (e.g. the inline worker task) wait instead of
        # failing with "database is locked".
        kwargs["connect_args"] = {"timeout": 30}
    else:
        kwargs["pool_size"] = settings.db_pool_size
        kwargs["max_overflow"] = settings.db_max_overflow
    return create_async_engine(settings.database_url, **kwargs)


engine: AsyncEngine = _build_engine()
SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine, expire_on_commit=False, autoflush=False
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a session and guarantee rollback-on-error / close semantics."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def create_all() -> None:
    """Create tables from metadata (dev/test convenience; prod uses Alembic)."""
    # Import models so they register on Base.metadata before create_all.
    from aegis.db import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    await engine.dispose()

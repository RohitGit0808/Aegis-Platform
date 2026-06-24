"""Alembic migration environment (async).

The target metadata is :data:`aegis.db.base.Base.metadata`. We import
``aegis.db.models`` for its side effect of registering every ORM model on that
metadata, so autogenerate sees the full schema. The database URL is sourced from
the application settings (``AEGIS_DATABASE_URL`` / .env), keeping a single source
of truth, and migrations run over an async engine.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Populate Base.metadata: importing models registers all tables/constraints.
import aegis.db.models  # noqa: F401
from aegis.core.config import settings
from aegis.db.base import Base

# Alembic Config object — provides access to alembic.ini values.
config = context.config

# Override the placeholder URL with the app's runtime setting.
config.set_main_option("sqlalchemy.url", settings.database_url)

# Configure Python logging from the ini file, if present.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The naming convention lives on Base.metadata, so generated names are stable
# and reversible across SQLite (dev/CI) and Postgres (prod).
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a DB connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        render_as_batch=url is not None and url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Configure the context against a live connection and run migrations."""
    is_sqlite = connection.dialect.name == "sqlite"
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        # SQLite cannot ALTER most columns; batch mode rebuilds tables instead.
        render_as_batch=is_sqlite,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Create an async engine and run migrations against it."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())

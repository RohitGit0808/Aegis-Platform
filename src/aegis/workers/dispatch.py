"""Run dispatch — decouples "a run was requested" from "where it executes".

Two interchangeable backends behind one :class:`RunDispatcher` protocol:

* :class:`ArqDispatcher` enqueues onto Redis for a horizontally-scalable pool of
  out-of-process arq workers (the production path).
* :class:`InlineDispatcher` runs the executor as an in-process background task —
  zero infrastructure, ideal for local dev, tests and demos.

The backend is chosen automatically from configuration, so the API code that
calls ``enqueue`` never changes.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Protocol

from aegis.core.config import settings
from aegis.core.logging import get_logger
from aegis.workers.executor import execute_run

log = get_logger(__name__)

# Hold strong references so background tasks aren't garbage-collected mid-flight.
_background_tasks: set[asyncio.Task[None]] = set()


class RunDispatcher(Protocol):
    async def enqueue(self, run_id: uuid.UUID) -> None: ...


class InlineDispatcher:
    async def enqueue(self, run_id: uuid.UUID) -> None:
        task = asyncio.create_task(execute_run(run_id))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)


class ArqDispatcher:
    def __init__(self) -> None:
        self._pool: Any = None

    async def enqueue(self, run_id: uuid.UUID) -> None:
        from arq import create_pool
        from arq.connections import RedisSettings

        if self._pool is None:
            self._pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await self._pool.enqueue_job("execute_run_task", str(run_id))


_dispatcher: RunDispatcher | None = None


def get_dispatcher() -> RunDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = InlineDispatcher() if settings.use_fake_cache else ArqDispatcher()
        log.info("dispatcher.selected", kind=type(_dispatcher).__name__)
    return _dispatcher

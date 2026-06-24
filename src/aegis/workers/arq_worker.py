"""arq worker entrypoint.

Run with:  ``arq aegis.workers.arq_worker.WorkerSettings``

Requires ``AEGIS_REDIS_URL`` to be set (the in-process InlineDispatcher is used
otherwise and no separate worker is needed).
"""

from __future__ import annotations

from typing import Any, ClassVar

from arq.connections import RedisSettings

from aegis.core.config import settings
from aegis.core.logging import configure_logging, get_logger
from aegis.workers.tasks import execute_run_task

log = get_logger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging()
    log.info("worker.startup", concurrency=settings.worker_concurrency)


async def shutdown(ctx: dict[str, Any]) -> None:
    log.info("worker.shutdown")


class WorkerSettings:
    functions: ClassVar[list[Any]] = [execute_run_task]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = settings.worker_concurrency
    redis_settings = RedisSettings.from_dsn(settings.redis_url or "redis://localhost:6379/0")

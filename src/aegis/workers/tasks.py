"""arq task wrappers. Thin adapters over the executor so the worker module stays
free of business logic."""

from __future__ import annotations

import uuid
from typing import Any

from aegis.workers.executor import execute_run


async def execute_run_task(ctx: dict[str, Any], run_id: str) -> None:
    await execute_run(uuid.UUID(run_id))

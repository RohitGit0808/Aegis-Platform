"""Test-run and step-result persistence."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from aegis.db.models import StepResult, TestRun
from aegis.repositories.base import BaseRepository


class RunRepository(BaseRepository[TestRun]):
    model = TestRun

    async def get_with_results(self, run_id: uuid.UUID) -> TestRun | None:
        stmt = select(TestRun).where(TestRun.id == run_id).options(selectinload(TestRun.results))
        return await self.session.scalar(stmt)

    async def get_by_idempotency_key(self, key: str) -> TestRun | None:
        stmt = select(TestRun).where(TestRun.idempotency_key == key)
        return await self.session.scalar(stmt)

    async def add_step_result(self, result: StepResult) -> StepResult:
        self.session.add(result)
        await self.session.flush()
        return result

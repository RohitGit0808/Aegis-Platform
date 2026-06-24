"""Test-run orchestration: creation (idempotent), querying and cancellation.

The service persists the run and reports whether it was newly created; the API
layer commits the unit of work and then asks the dispatcher to enqueue execution
(so the worker never races a row that isn't committed yet).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from aegis.core.exceptions import ForbiddenError, NotFoundError
from aegis.core.pagination import PaginationParams
from aegis.db.models import TestRun, User
from aegis.domain.enums import RunStatus, UserRole
from aegis.domain.schemas import RunCreate
from aegis.repositories.runs import RunRepository
from aegis.repositories.suites import SuiteRepository


class RunService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.runs = RunRepository(session)
        self.suites = SuiteRepository(session)

    async def create(
        self,
        suite_id: uuid.UUID,
        data: RunCreate,
        actor: User,
        *,
        idempotency_key: str | None = None,
    ) -> tuple[TestRun, bool]:
        """Return (run, created). On a replayed idempotency key, created is False."""
        if idempotency_key:
            existing = await self.runs.get_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing, False

        suite = await self.suites.get_with_cases(suite_id)
        if suite is None:
            raise NotFoundError("Test suite not found.")
        if actor.role is not UserRole.ADMIN and suite.owner_id != actor.id:
            raise ForbiddenError("You do not own this suite.", code="not_owner")

        run = TestRun(
            suite_id=suite.id,
            trigger=data.trigger,
            created_by_id=actor.id,
            idempotency_key=idempotency_key,
            total_cases=len(suite.cases),
            status=RunStatus.QUEUED,
        )
        await self.runs.add(run)
        return run, True

    async def get(self, run_id: uuid.UUID) -> TestRun:
        run = await self.runs.get_with_results(run_id)
        if run is None:
            raise NotFoundError("Test run not found.")
        return run

    async def list(
        self, pagination: PaginationParams, *, suite_id: uuid.UUID | None = None
    ) -> tuple[list[TestRun], int]:
        filters = [TestRun.suite_id == suite_id] if suite_id is not None else []
        return await self.runs.list(
            *filters, pagination=pagination, order_by=TestRun.created_at.desc()
        )

    async def cancel(self, run_id: uuid.UUID, actor: User) -> TestRun:
        run = await self.get(run_id)
        if actor.role is not UserRole.ADMIN and run.created_by_id != actor.id:
            raise ForbiddenError("You can only cancel runs you created.", code="not_owner")
        if not run.status.is_terminal:
            run.status = RunStatus.CANCELLED
            await self.session.flush()
        return run

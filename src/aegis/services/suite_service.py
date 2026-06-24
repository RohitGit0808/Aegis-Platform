"""Test-suite and test-case management."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from aegis.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from aegis.core.pagination import PaginationParams
from aegis.db.models import TestCase, TestSuite, User
from aegis.domain.enums import UserRole
from aegis.domain.schemas import SuiteCreate, SuiteUpdate, TestCaseCreate
from aegis.repositories.suites import SuiteRepository


def _assert_can_mutate(suite: TestSuite, actor: User) -> None:
    """Object-level authorization: only the owner (or an admin) may mutate a suite."""
    if actor.role is not UserRole.ADMIN and suite.owner_id != actor.id:
        raise ForbiddenError("You do not own this suite.", code="not_owner")


class SuiteService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = SuiteRepository(session)

    async def create(self, data: SuiteCreate, owner_id: uuid.UUID) -> TestSuite:
        if await self.repo.get_by_slug(data.slug):
            raise ConflictError(f"Slug '{data.slug}' is already taken.", code="slug_taken")
        suite = TestSuite(
            name=data.name,
            slug=data.slug,
            description=data.description,
            target_base_url=data.target_base_url,
            tags=data.tags,
            owner_id=owner_id,
        )
        for case in data.cases:
            suite.cases.append(self._build_case(case))
        return await self.repo.add(suite)

    async def list(self, pagination: PaginationParams) -> tuple[list[TestSuite], int]:
        return await self.repo.list(pagination=pagination, order_by=TestSuite.created_at.desc())

    async def get(self, suite_id: uuid.UUID) -> TestSuite:
        suite = await self.repo.get_with_cases(suite_id)
        if suite is None:
            raise NotFoundError("Test suite not found.")
        return suite

    async def update(self, suite_id: uuid.UUID, data: SuiteUpdate, actor: User) -> TestSuite:
        suite = await self.get(suite_id)
        _assert_can_mutate(suite, actor)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(suite, field, value)
        await self.session.flush()
        return suite

    async def delete(self, suite_id: uuid.UUID, actor: User) -> None:
        suite = await self.get(suite_id)
        _assert_can_mutate(suite, actor)
        await self.repo.delete(suite)

    async def add_case(self, suite_id: uuid.UUID, data: TestCaseCreate, actor: User) -> TestCase:
        suite = await self.get(suite_id)
        _assert_can_mutate(suite, actor)
        case = self._build_case(data)
        suite.cases.append(case)
        await self.session.flush()
        return case

    @staticmethod
    def _build_case(data: TestCaseCreate) -> TestCase:
        return TestCase(
            name=data.name,
            order_index=data.order_index,
            steps=[step.model_dump(mode="json") for step in data.steps],
        )

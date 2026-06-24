"""Test-suite and test-case persistence."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from aegis.db.models import TestSuite
from aegis.repositories.base import BaseRepository


class SuiteRepository(BaseRepository[TestSuite]):
    model = TestSuite

    async def get_by_slug(self, slug: str) -> TestSuite | None:
        return await self.session.scalar(select(TestSuite).where(TestSuite.slug == slug))

    async def get_with_cases(self, suite_id: uuid.UUID) -> TestSuite | None:
        stmt = (
            select(TestSuite).where(TestSuite.id == suite_id).options(selectinload(TestSuite.cases))
        )
        return await self.session.scalar(stmt)

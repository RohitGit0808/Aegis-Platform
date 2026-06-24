"""Generic async repository — the single place that talks to the ORM.

Repositories encapsulate persistence so services stay free of SQLAlchemy
details and are trivially unit-testable. The base provides typed CRUD and
offset pagination; concrete repositories add aggregate-specific queries.
"""

from __future__ import annotations

import uuid
from typing import Any, Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from aegis.core.pagination import PaginationParams
from aegis.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, entity_id: uuid.UUID) -> ModelT | None:
        return await self.session.get(self.model, entity_id)

    async def add(self, instance: ModelT) -> ModelT:
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def delete(self, instance: ModelT) -> None:
        await self.session.delete(instance)
        await self.session.flush()

    async def count(self, *filters: ColumnElement[bool]) -> int:
        stmt = select(func.count()).select_from(self.model)
        if filters:
            stmt = stmt.where(*filters)
        return int((await self.session.scalar(stmt)) or 0)

    async def list(
        self,
        *filters: ColumnElement[bool],
        pagination: PaginationParams,
        order_by: ColumnElement[Any] | None = None,
    ) -> tuple[list[ModelT], int]:
        stmt = select(self.model)
        if filters:
            stmt = stmt.where(*filters)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        stmt = stmt.limit(pagination.limit).offset(pagination.offset)

        rows = list((await self.session.scalars(stmt)).all())
        total = await self.count(*filters)
        return rows, total

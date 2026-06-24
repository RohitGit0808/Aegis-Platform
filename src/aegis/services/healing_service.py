"""Healing-event querying and human review (accept / reject a proposed locator)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from aegis.core.exceptions import NotFoundError
from aegis.db.models import HealingEvent
from aegis.repositories.healing import HealingRepository


class HealingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = HealingRepository(session)

    async def list_for_run(self, run_id: uuid.UUID) -> list[HealingEvent]:
        return await self.repo.list_for_run(run_id)

    async def review(self, event_id: uuid.UUID, *, accepted: bool) -> HealingEvent:
        event = await self.repo.get(event_id)
        if event is None:
            raise NotFoundError("Healing event not found.")
        event.accepted = accepted
        await self.session.flush()
        return event

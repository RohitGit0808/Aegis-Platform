"""Healing-event persistence."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from aegis.db.models import HealingEvent
from aegis.repositories.base import BaseRepository


class HealingRepository(BaseRepository[HealingEvent]):
    model = HealingEvent

    async def list_for_run(self, run_id: uuid.UUID) -> list[HealingEvent]:
        stmt = (
            select(HealingEvent)
            .where(HealingEvent.run_id == run_id)
            .order_by(HealingEvent.created_at)
        )
        return list((await self.session.scalars(stmt)).all())

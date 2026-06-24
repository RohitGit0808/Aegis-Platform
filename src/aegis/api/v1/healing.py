"""Healing-event endpoints: list per run, and human review (accept/reject)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from aegis.api.deps import CurrentUser, SessionDep, require_roles
from aegis.db.models import User
from aegis.domain.enums import UserRole
from aegis.domain.schemas import HealingEventRead, HealingReviewRequest
from aegis.services.healing_service import HealingService

router = APIRouter(tags=["healing"])

Engineer = Annotated[User, Depends(require_roles(UserRole.ENGINEER))]


@router.get("/runs/{run_id}/healing", response_model=list[HealingEventRead])
async def list_healing_events(
    run_id: uuid.UUID, session: SessionDep, _: CurrentUser
) -> list[HealingEventRead]:
    events = await HealingService(session).list_for_run(run_id)
    return [HealingEventRead.model_validate(event) for event in events]


@router.post("/healing/{event_id}/review", response_model=HealingEventRead)
async def review_healing_event(
    event_id: uuid.UUID,
    body: HealingReviewRequest,
    session: SessionDep,
    user: Engineer,
) -> HealingEventRead:
    event = await HealingService(session).review(event_id, accepted=body.accepted)
    await session.commit()
    return HealingEventRead.model_validate(event)

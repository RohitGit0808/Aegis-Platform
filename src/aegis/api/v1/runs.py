"""Test-run endpoints: trigger (idempotent), list, fetch, cancel."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from aegis.api.deps import (
    CurrentUser,
    IdempotencyKey,
    Pagination,
    SessionDep,
    require_roles,
)
from aegis.db.models import User
from aegis.domain.enums import UserRole
from aegis.domain.schemas import Page, RunCreate, RunDetail, RunRead
from aegis.services.run_service import RunService
from aegis.workers.dispatch import get_dispatcher

router = APIRouter(tags=["runs"])

Engineer = Annotated[User, Depends(require_roles(UserRole.ENGINEER))]


@router.post(
    "/suites/{suite_id}/runs", response_model=RunRead, status_code=status.HTTP_202_ACCEPTED
)
async def trigger_run(
    suite_id: uuid.UUID,
    data: RunCreate,
    session: SessionDep,
    user: Engineer,
    idempotency_key: IdempotencyKey = None,
) -> RunRead:
    service = RunService(session)
    run, created = await service.create(suite_id, data, user, idempotency_key=idempotency_key)
    await session.commit()
    if created:
        await get_dispatcher().enqueue(run.id)
    return RunRead.model_validate(run)


@router.get("/runs", response_model=Page[RunRead])
async def list_runs(
    session: SessionDep,
    pagination: Pagination,
    _: CurrentUser,
    suite_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[RunRead]:
    items, total = await RunService(session).list(pagination, suite_id=suite_id)
    return Page[RunRead].create([RunRead.model_validate(item) for item in items], total, pagination)


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(run_id: uuid.UUID, session: SessionDep, _: CurrentUser) -> RunDetail:
    return RunDetail.model_validate(await RunService(session).get(run_id))


@router.post("/runs/{run_id}/cancel", response_model=RunRead)
async def cancel_run(run_id: uuid.UUID, session: SessionDep, user: Engineer) -> RunRead:
    run = await RunService(session).cancel(run_id, user)
    await session.commit()
    return RunRead.model_validate(run)

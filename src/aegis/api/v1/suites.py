"""Test-suite and test-case CRUD."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from aegis.api.deps import CurrentUser, Pagination, SessionDep, require_roles
from aegis.db.models import User
from aegis.domain.enums import UserRole
from aegis.domain.schemas import (
    Page,
    SuiteCreate,
    SuiteDetail,
    SuiteRead,
    SuiteUpdate,
    TestCaseCreate,
    TestCaseRead,
)
from aegis.services.suite_service import SuiteService

router = APIRouter(prefix="/suites", tags=["suites"])

Engineer = Annotated[User, Depends(require_roles(UserRole.ENGINEER))]


@router.post("", response_model=SuiteDetail, status_code=status.HTTP_201_CREATED)
async def create_suite(data: SuiteCreate, session: SessionDep, user: Engineer) -> SuiteDetail:
    service = SuiteService(session)
    suite = await service.create(data, user.id)
    await session.commit()
    return SuiteDetail.model_validate(await service.get(suite.id))


@router.get("", response_model=Page[SuiteRead])
async def list_suites(
    session: SessionDep, pagination: Pagination, _: CurrentUser
) -> Page[SuiteRead]:
    items, total = await SuiteService(session).list(pagination)
    return Page[SuiteRead].create(
        [SuiteRead.model_validate(item) for item in items], total, pagination
    )


@router.get("/{suite_id}", response_model=SuiteDetail)
async def get_suite(suite_id: uuid.UUID, session: SessionDep, _: CurrentUser) -> SuiteDetail:
    return SuiteDetail.model_validate(await SuiteService(session).get(suite_id))


@router.patch("/{suite_id}", response_model=SuiteDetail)
async def update_suite(
    suite_id: uuid.UUID, data: SuiteUpdate, session: SessionDep, user: Engineer
) -> SuiteDetail:
    service = SuiteService(session)
    await service.update(suite_id, data, user)
    await session.commit()
    return SuiteDetail.model_validate(await service.get(suite_id))


@router.delete("/{suite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_suite(suite_id: uuid.UUID, session: SessionDep, user: Engineer) -> None:
    await SuiteService(session).delete(suite_id, user)
    await session.commit()


@router.post("/{suite_id}/cases", response_model=TestCaseRead, status_code=status.HTTP_201_CREATED)
async def add_case(
    suite_id: uuid.UUID, data: TestCaseCreate, session: SessionDep, user: Engineer
) -> TestCaseRead:
    service = SuiteService(session)
    case = await service.add_case(suite_id, data, user)
    await session.commit()
    return TestCaseRead.model_validate(case)

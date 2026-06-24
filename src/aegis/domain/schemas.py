"""Pydantic v2 DTOs — the wire/API contract.

These are deliberately decoupled from the ORM models: requests are validated
into ``*Create``/``*Update`` schemas, and responses are serialised from ORM
instances via ``from_attributes``. The generic :class:`Page` envelope provides
consistent, typed pagination across every list endpoint.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from aegis.core.pagination import PaginationParams
from aegis.domain.enums import (
    HealingStrategy,
    RunStatus,
    RunTrigger,
    StepAction,
    StepStatus,
    UserRole,
)

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- #
# Envelopes
# --------------------------------------------------------------------------- #
class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorDetail


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int
    pages: int

    @classmethod
    def create(cls, items: list[T], total: int, params: PaginationParams) -> Page[T]:
        pages = (total + params.size - 1) // params.size if params.size else 0
        return cls(items=items, total=total, page=params.page, size=params.size, pages=pages)


# --------------------------------------------------------------------------- #
# Auth & users
# --------------------------------------------------------------------------- #
class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenRefreshRequest(BaseModel):
    refresh_token: str


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    role: UserRole = UserRole.ENGINEER


class UserRead(ORMModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime


# --------------------------------------------------------------------------- #
# Suites & cases
# --------------------------------------------------------------------------- #
class StepSpec(BaseModel):
    action: StepAction
    selector: str | None = Field(default=None, max_length=1024)
    value: str | None = Field(default=None, max_length=4096)
    expected: str | None = Field(default=None, max_length=4096)


class TestCaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    order_index: int = 0
    steps: list[StepSpec] = Field(default_factory=list)


class TestCaseRead(ORMModel):
    id: uuid.UUID
    suite_id: uuid.UUID
    name: str
    order_index: int
    is_active: bool
    steps: list[StepSpec]


class SuiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255, pattern=r"^[a-z0-9][a-z0-9-]*$")
    description: str | None = None
    target_base_url: str = Field(max_length=2048)
    tags: list[str] = Field(default_factory=list)
    cases: list[TestCaseCreate] = Field(default_factory=list)


class SuiteUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    target_base_url: str | None = Field(default=None, max_length=2048)
    tags: list[str] | None = None
    is_active: bool | None = None


class SuiteRead(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    target_base_url: str
    tags: list[str]
    is_active: bool
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class SuiteDetail(SuiteRead):
    cases: list[TestCaseRead] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Runs & results
# --------------------------------------------------------------------------- #
class RunCreate(BaseModel):
    trigger: RunTrigger = RunTrigger.MANUAL


class StepResultRead(ORMModel):
    id: uuid.UUID
    case_name: str
    step_index: int
    action: StepAction
    status: StepStatus
    original_selector: str | None
    healed_selector: str | None
    message: str | None
    duration_ms: int


class RunRead(ORMModel):
    id: uuid.UUID
    suite_id: uuid.UUID
    status: RunStatus
    trigger: RunTrigger
    total_cases: int
    passed_count: int
    failed_count: int
    healed_count: int
    duration_ms: int | None
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class RunDetail(RunRead):
    results: list[StepResultRead] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Healing
# --------------------------------------------------------------------------- #
class HealingEventRead(ORMModel):
    id: uuid.UUID
    run_id: uuid.UUID
    original_selector: str
    healed_selector: str | None
    strategy: HealingStrategy
    confidence: float
    rationale: str | None
    succeeded: bool
    accepted: bool | None
    created_at: datetime


class HealingReviewRequest(BaseModel):
    accepted: bool


class HealingProposal(BaseModel):
    """Output of the self-healing engine for a single broken locator."""

    healed_selector: str | None
    strategy: HealingStrategy
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str

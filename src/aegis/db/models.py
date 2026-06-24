"""SQLAlchemy ORM models — the persistence-side domain model.

Enums are stored as portable VARCHAR (``native_enum=False``) so the same schema
works identically on SQLite (local/CI) and Postgres (production) without native
enum-type migrations. Foreign keys cascade so deleting a suite cleanly removes
its cases, runs, results and healing events.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aegis.db.base import Base, TimestampMixin, UUIDMixin
from aegis.domain.enums import (
    HealingStrategy,
    RunStatus,
    RunTrigger,
    StepAction,
    StepStatus,
    UserRole,
)


def _enum(enum_cls: type) -> SAEnum:
    return SAEnum(enum_cls, native_enum=False, length=32, validate_strings=True)


class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(_enum(UserRole), default=UserRole.ENGINEER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    suites: Mapped[list[TestSuite]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class TestSuite(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "test_suites"

    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    target_base_url: Mapped[str] = mapped_column(String(2048))
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    owner: Mapped[User] = relationship(back_populates="suites")
    cases: Mapped[list[TestCase]] = relationship(
        back_populates="suite",
        cascade="all, delete-orphan",
        order_by="TestCase.order_index",
    )
    runs: Mapped[list[TestRun]] = relationship(back_populates="suite", cascade="all, delete-orphan")


class TestCase(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "test_cases"

    suite_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_suites.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Each step: {"action", "selector", "value", "expected"}.
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    suite: Mapped[TestSuite] = relationship(back_populates="cases")


class TestRun(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "test_runs"

    suite_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_suites.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[RunStatus] = mapped_column(
        _enum(RunStatus), default=RunStatus.QUEUED, index=True
    )
    trigger: Mapped[RunTrigger] = mapped_column(_enum(RunTrigger), default=RunTrigger.MANUAL)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255), default=None, index=True)

    total_cases: Mapped[int] = mapped_column(Integer, default=0)
    passed_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    healed_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)

    suite: Mapped[TestSuite] = relationship(back_populates="runs")
    results: Mapped[list[StepResult]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    healing_events: Mapped[list[HealingEvent]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class StepResult(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "step_results"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_runs.id", ondelete="CASCADE"), index=True
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    case_name: Mapped[str] = mapped_column(String(255))
    step_index: Mapped[int] = mapped_column(Integer)
    action: Mapped[StepAction] = mapped_column(_enum(StepAction))
    status: Mapped[StepStatus] = mapped_column(_enum(StepStatus))
    original_selector: Mapped[str | None] = mapped_column(String(1024), default=None)
    healed_selector: Mapped[str | None] = mapped_column(String(1024), default=None)
    message: Mapped[str | None] = mapped_column(Text, default=None)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)

    run: Mapped[TestRun] = relationship(back_populates="results")


class HealingEvent(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "healing_events"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_runs.id", ondelete="CASCADE"), index=True
    )
    step_result_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    original_selector: Mapped[str] = mapped_column(String(1024))
    healed_selector: Mapped[str | None] = mapped_column(String(1024), default=None)
    strategy: Mapped[HealingStrategy] = mapped_column(_enum(HealingStrategy))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    dom_snapshot_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    rationale: Mapped[str | None] = mapped_column(Text, default=None)
    succeeded: Mapped[bool] = mapped_column(Boolean, default=False)
    # None = pending human review, True = accepted, False = rejected.
    accepted: Mapped[bool | None] = mapped_column(Boolean, default=None)

    run: Mapped[TestRun] = relationship(back_populates="healing_events")

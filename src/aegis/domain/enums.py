"""Domain enumerations shared by ORM models, DTOs and services."""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    ENGINEER = "engineer"
    VIEWER = "viewer"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {
            RunStatus.PASSED,
            RunStatus.FAILED,
            RunStatus.ERROR,
            RunStatus.CANCELLED,
        }


class RunTrigger(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    CI = "ci"
    WEBHOOK = "webhook"


class StepAction(StrEnum):
    NAVIGATE = "navigate"
    CLICK = "click"
    FILL = "fill"
    ASSERT_TEXT = "assert_text"
    ASSERT_VISIBLE = "assert_visible"
    WAIT = "wait"


class StepStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    HEALED = "healed"
    SKIPPED = "skipped"


class HealingStrategy(StrEnum):
    NONE = "none"
    HEURISTIC = "heuristic"
    LLM = "llm"
    HYBRID = "hybrid"

"""Initial schema.

Creates the core tables: users, test_suites, test_cases, test_runs,
step_results and healing_events. Enums are stored as portable VARCHAR(32)
(``native_enum=False`` in the models) so the schema is identical on SQLite and
Postgres. UUID primary keys use ``sa.Uuid`` (CHAR(32) on SQLite, native uuid on
Postgres). Constraint names follow the project naming convention on
``Base.metadata`` so they match autogenerate output exactly.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-24 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Enum value sets stored as VARCHAR — kept in sync with aegis.domain.enums.
_USER_ROLES = ("admin", "engineer", "viewer")
_RUN_STATUS = ("queued", "running", "passed", "failed", "error", "cancelled")
_RUN_TRIGGER = ("manual", "scheduled", "ci", "webhook")
_STEP_ACTION = ("navigate", "click", "fill", "assert_text", "assert_visible", "wait")
_STEP_STATUS = ("passed", "failed", "healed", "skipped")
_HEALING_STRATEGY = ("none", "heuristic", "llm", "hybrid")


def _enum(values: tuple[str, ...], name: str) -> sa.Enum:
    return sa.Enum(*values, native_enum=False, length=32, validate_strings=True, name=name)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("role", _enum(_USER_ROLES, "userrole"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "test_suites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("target_base_url", sa.String(length=2048), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_test_suites_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_suites")),
    )
    op.create_index(op.f("ix_test_suites_slug"), "test_suites", ["slug"], unique=True)
    op.create_index(op.f("ix_test_suites_owner_id"), "test_suites", ["owner_id"], unique=False)

    op.create_table(
        "test_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("suite_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["suite_id"],
            ["test_suites.id"],
            name=op.f("fk_test_cases_suite_id_test_suites"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_cases")),
    )
    op.create_index(op.f("ix_test_cases_suite_id"), "test_cases", ["suite_id"], unique=False)

    op.create_table(
        "test_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("suite_id", sa.Uuid(), nullable=False),
        sa.Column("status", _enum(_RUN_STATUS, "runstatus"), nullable=False),
        sa.Column("trigger", _enum(_RUN_TRIGGER, "runtrigger"), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("total_cases", sa.Integer(), nullable=False),
        sa.Column("passed_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("healed_count", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["suite_id"],
            ["test_suites.id"],
            name=op.f("fk_test_runs_suite_id_test_suites"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_test_runs_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_runs")),
    )
    op.create_index(op.f("ix_test_runs_suite_id"), "test_runs", ["suite_id"], unique=False)
    op.create_index(op.f("ix_test_runs_status"), "test_runs", ["status"], unique=False)
    op.create_index(
        op.f("ix_test_runs_idempotency_key"), "test_runs", ["idempotency_key"], unique=False
    )

    op.create_table(
        "step_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=True),
        sa.Column("case_name", sa.String(length=255), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("action", _enum(_STEP_ACTION, "stepaction"), nullable=False),
        sa.Column("status", _enum(_STEP_STATUS, "stepstatus"), nullable=False),
        sa.Column("original_selector", sa.String(length=1024), nullable=True),
        sa.Column("healed_selector", sa.String(length=1024), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["test_runs.id"],
            name=op.f("fk_step_results_run_id_test_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_step_results")),
    )
    op.create_index(op.f("ix_step_results_run_id"), "step_results", ["run_id"], unique=False)

    op.create_table(
        "healing_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_result_id", sa.Uuid(), nullable=True),
        sa.Column("original_selector", sa.String(length=1024), nullable=False),
        sa.Column("healed_selector", sa.String(length=1024), nullable=True),
        sa.Column("strategy", _enum(_HEALING_STRATEGY, "healingstrategy"), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("dom_snapshot_hash", sa.String(length=64), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["test_runs.id"],
            name=op.f("fk_healing_events_run_id_test_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_healing_events")),
    )
    op.create_index(op.f("ix_healing_events_run_id"), "healing_events", ["run_id"], unique=False)


def downgrade() -> None:
    # Reverse dependency order: children before parents.
    op.drop_index(op.f("ix_healing_events_run_id"), table_name="healing_events")
    op.drop_table("healing_events")

    op.drop_index(op.f("ix_step_results_run_id"), table_name="step_results")
    op.drop_table("step_results")

    op.drop_index(op.f("ix_test_runs_idempotency_key"), table_name="test_runs")
    op.drop_index(op.f("ix_test_runs_status"), table_name="test_runs")
    op.drop_index(op.f("ix_test_runs_suite_id"), table_name="test_runs")
    op.drop_table("test_runs")

    op.drop_index(op.f("ix_test_cases_suite_id"), table_name="test_cases")
    op.drop_table("test_cases")

    op.drop_index(op.f("ix_test_suites_owner_id"), table_name="test_suites")
    op.drop_index(op.f("ix_test_suites_slug"), table_name="test_suites")
    op.drop_table("test_suites")

    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")

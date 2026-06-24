"""Aegis admin CLI (Typer).

aegis version
aegis serve [--host] [--port] [--reload]
aegis create-user EMAIL PASSWORD [--full-name] [--role]
aegis seed            # create an admin + a demo suite that exercises healing
"""

from __future__ import annotations

import asyncio

import typer

from aegis import __version__
from aegis.core.exceptions import ConflictError
from aegis.core.logging import configure_logging, get_logger
from aegis.domain.enums import StepAction, UserRole
from aegis.domain.schemas import StepSpec, SuiteCreate, TestCaseCreate, UserCreate

app = typer.Typer(help="Aegis administration CLI.", no_args_is_help=True)
log = get_logger(__name__)


@app.command()
def version() -> None:
    """Print the platform version."""
    typer.echo(__version__)


@app.command()
def serve(
    # Binding all interfaces is intentional for containerized serving.
    host: str = "0.0.0.0",  # noqa: S104  # nosec B104
    port: int = 8000,
    reload: bool = False,
) -> None:
    """Run the API with uvicorn."""
    import uvicorn

    uvicorn.run("aegis.main:app", host=host, port=port, reload=reload)


@app.command()
def create_user(
    email: str,
    password: str,
    full_name: str = "Aegis User",
    role: str = "engineer",
) -> None:
    """Create a user account."""
    asyncio.run(_create_user(email, password, full_name, UserRole(role)))


@app.command()
def seed() -> None:
    """Seed an admin account and a demo suite (passes, heals, and a real failure)."""
    asyncio.run(_seed())


# --------------------------------------------------------------------------- #
async def _create_user(email: str, password: str, full_name: str, role: UserRole) -> None:
    configure_logging()
    from aegis.db.session import SessionLocal, create_all, dispose_engine
    from aegis.services.auth_service import AuthService

    await create_all()
    async with SessionLocal() as session:
        service = AuthService(session)
        try:
            user = await service.register(
                UserCreate(email=email, password=password, full_name=full_name, role=role)
            )
            await session.commit()
            typer.echo(f"Created {user.email} with role {user.role.value}.")
        except ConflictError:
            typer.echo(f"User {email} already exists.")
    await dispose_engine()


def _demo_suite() -> SuiteCreate:
    return SuiteCreate(
        name="Aegis Demo — Authentication & Dashboard",
        slug="aegis-demo",
        description="Showcase suite: stable locators pass, brittle ones self-heal, "
        "and a purely structural locator fails honestly.",
        target_base_url="https://demo.aegis.dev",
        tags=["demo", "smoke"],
        cases=[
            TestCaseCreate(
                name="Authentication",
                order_index=0,
                steps=[
                    StepSpec(action=StepAction.NAVIGATE, value="/login"),
                    StepSpec(
                        action=StepAction.FILL,
                        selector='[data-testid="email"]',
                        value="qa@aegis.dev",
                    ),
                    StepSpec(
                        action=StepAction.FILL,
                        selector='[data-testid="password"]',
                        value="pa55word",
                    ),
                    # Brittle #id locator — heals via data-testid (high confidence).
                    StepSpec(
                        action=StepAction.CLICK,
                        selector='button.btn-primary[data-testid="submit"]#old-submit-btn',
                    ),
                    # Text locator drift — heals at low confidence, flagged for human review.
                    StepSpec(
                        action=StepAction.ASSERT_TEXT,
                        selector="text=Welcome",
                        expected="Welcome to Aegis",
                    ),
                ],
            ),
            TestCaseCreate(
                name="Dashboard",
                order_index=1,
                steps=[
                    StepSpec(action=StepAction.NAVIGATE, value="/dashboard"),
                    StepSpec(action=StepAction.ASSERT_VISIBLE, selector='[data-testid="nav-bar"]'),
                    # Pure structural locator — no recoverable signal, fails honestly.
                    StepSpec(action=StepAction.CLICK, selector="nav > ul:nth-child(5)"),
                    StepSpec(
                        action=StepAction.ASSERT_TEXT,
                        selector='[data-testid="user-greeting"]',
                        expected="Hello",
                    ),
                ],
            ),
        ],
    )


async def _seed() -> None:
    configure_logging()
    from aegis.db.session import SessionLocal, create_all, dispose_engine
    from aegis.services.auth_service import AuthService
    from aegis.services.suite_service import SuiteService

    await create_all()
    async with SessionLocal() as session:
        auth = AuthService(session)
        try:
            admin = await auth.register(
                UserCreate(
                    email="admin@aegis.dev",
                    password="aegis-admin-pw",
                    full_name="Aegis Admin",
                    role=UserRole.ADMIN,
                )
            )
            await session.commit()
            typer.echo("Created admin@aegis.dev (password: aegis-admin-pw)")
        except ConflictError:
            admin = await auth.users.get_by_email("admin@aegis.dev")  # type: ignore[assignment]
            typer.echo("admin@aegis.dev already exists.")

        suites = SuiteService(session)
        try:
            suite = await suites.create(_demo_suite(), admin.id)
            await session.commit()
            typer.echo(f"Created demo suite '{suite.slug}' with {len(suite.cases)} cases.")
        except ConflictError:
            typer.echo("Demo suite already exists.")
    await dispose_engine()
    typer.echo("Seed complete. Log in, then POST /api/v1/suites/{id}/runs to see healing.")


if __name__ == "__main__":
    app()

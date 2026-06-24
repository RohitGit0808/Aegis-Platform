"""FastAPI application factory, lifespan, middleware and infra endpoints."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from aegis import __version__
from aegis.api.errors import register_exception_handlers
from aegis.api.router import api_router
from aegis.cache.redis import close_cache, get_cache
from aegis.core.config import Environment, settings
from aegis.core.logging import configure_logging, get_logger
from aegis.core.metrics import render_metrics
from aegis.core.observability import add_observability_middleware, setup_tracing
from aegis.db.session import create_all, dispose_engine, engine

log = get_logger(__name__)

_DESCRIPTION = (
    "Aegis is a distributed, AI-powered self-healing test-orchestration platform. "
    "Register test suites, trigger runs across an async worker pool, stream results "
    "live, and let the self-healing engine recover broken UI locators automatically."
)


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    configure_logging()
    log.info("app.startup", environment=settings.environment.value, version=__version__)
    # Dev/test bootstrap the schema directly; staging/prod use Alembic migrations.
    if settings.environment in (Environment.LOCAL, Environment.TEST):
        await create_all()
    yield
    await close_cache()
    await dispose_engine()
    log.info("app.shutdown")


def create_app() -> FastAPI:
    configure_logging()
    # Disable interactive docs / OpenAPI in production to limit surface exposure.
    docs_enabled = not settings.is_production
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=_DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    add_observability_middleware(app)
    register_exception_handlers(app)
    setup_tracing(app)

    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {"name": settings.app_name, "version": __version__, "docs": "/docs"}

    @app.get("/healthz", tags=["infra"], summary="Liveness probe")
    async def liveness() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/readyz", tags=["infra"], summary="Readiness probe")
    async def readiness() -> JSONResponse:
        db_ok = True
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:  # pragma: no cover - failure path
            db_ok = False
        cache_ok = await get_cache().ping()
        ready = db_ok and cache_ok
        return JSONResponse(
            status_code=200 if ready else 503,
            content={"ready": ready, "checks": {"database": db_ok, "cache": cache_ok}},
        )

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        if not settings.metrics_enabled:
            return Response(status_code=404)
        payload, content_type = render_metrics()
        return Response(content=payload, media_type=content_type)

    return app


app = create_app()

"""Service metadata endpoint (infra liveness/readiness live on the root app)."""

from __future__ import annotations

from fastapi import APIRouter

from aegis import __version__
from aegis.core.config import settings

router = APIRouter(tags=["meta"])


@router.get("/health", summary="Service info")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": __version__,
        "environment": settings.environment.value,
    }

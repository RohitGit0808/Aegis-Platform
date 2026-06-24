"""Aggregate v1 API router.

Rate limiting is applied to the HTTP routers but not the WebSocket route (its
dependency needs an HTTP ``Request``, which a WebSocket connection lacks).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from aegis.api.deps import rate_limiter
from aegis.api.v1 import auth, healing, health, runs, suites, ws

_rate_limited = [Depends(rate_limiter)]

api_router = APIRouter()
api_router.include_router(health.router, dependencies=_rate_limited)
api_router.include_router(auth.router, dependencies=_rate_limited)
api_router.include_router(suites.router, dependencies=_rate_limited)
api_router.include_router(runs.router, dependencies=_rate_limited)
api_router.include_router(healing.router, dependencies=_rate_limited)
api_router.include_router(ws.router)  # WebSocket: no HTTP-request rate-limit dep

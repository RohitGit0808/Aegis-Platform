"""WebSocket live run feed.

Subscribes to the cache pub/sub channel the executor publishes to and relays
every run/step event to the connected client in real time. Authentication is via
a ``token`` query parameter (WebSocket clients can't send Authorization headers
ergonomically); it is required in production and optional otherwise for easy
local exploration.
"""

from __future__ import annotations

import contextlib
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from aegis.cache.redis import get_cache
from aegis.core.config import Environment, settings
from aegis.core.logging import get_logger
from aegis.core.security import decode_token

router = APIRouter(tags=["streaming"])
log = get_logger(__name__)


def _authorized(token: str | None) -> bool:
    if token:
        try:
            decode_token(token, expected_type="access")
            return True
        except Exception:
            return False
    # A token is mandatory everywhere except truly-local development.
    return settings.environment is Environment.LOCAL


@router.websocket("/runs/{run_id}/stream")
async def stream_run(
    websocket: WebSocket, run_id: uuid.UUID, token: str | None = Query(default=None)
) -> None:
    if not _authorized(token):
        await websocket.close(code=1008)  # policy violation
        return

    await websocket.accept()
    channel = f"run:{run_id}"
    pubsub = get_cache().pubsub()
    await pubsub.subscribe(channel)
    try:
        async for message in pubsub.listen():
            if message.get("type") == "message":
                await websocket.send_text(message["data"])
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("ws.stream_error", error=str(exc))
    finally:
        with contextlib.suppress(Exception):  # pragma: no cover - cleanup is best-effort
            await pubsub.unsubscribe(channel)
            closer = getattr(pubsub, "aclose", None) or getattr(pubsub, "close", None)
            if closer is not None:
                result = closer()
                if hasattr(result, "__await__"):
                    await result

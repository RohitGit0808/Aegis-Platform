"""Request observability: correlation IDs, RED metrics, and optional OTel tracing.

The HTTP middleware stamps every request with a correlation id (propagated via
``X-Request-ID``), records request count and latency to Prometheus keyed by the
*route template* (not the raw path, to bound metric cardinality), and emits one
structured access log line. Distributed tracing is wired only when explicitly
enabled, and its (heavy) OpenTelemetry imports are deferred so the base install
stays lean.
"""

from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, Request

from aegis.core.config import settings
from aegis.core.logging import bind_correlation_id, get_logger
from aegis.core.metrics import HTTP_LATENCY, HTTP_REQUESTS

log = get_logger(__name__)


def add_observability_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def _observe(request: Request, call_next):  # type: ignore[no-untyped-def]
        correlation_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        bind_correlation_id(correlation_id)
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = time.perf_counter() - start
            route = request.scope.get("route")
            path = getattr(route, "path", request.url.path)
            HTTP_REQUESTS.labels(method=request.method, path=path, status=str(status_code)).inc()
            HTTP_LATENCY.labels(method=request.method, path=path).observe(duration)
            log.info(
                "http.request",
                method=request.method,
                path=path,
                status=status_code,
                duration_ms=round(duration * 1000, 2),
            )

    @app.middleware("http")
    async def _set_request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        cid = request.headers.get("X-Request-ID")
        if cid:
            response.headers["X-Request-ID"] = cid
        return response


def setup_tracing(app: FastAPI) -> None:
    if not settings.tracing_enabled:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        from aegis.db.session import engine

        provider = TracerProvider(
            resource=Resource.create({"service.name": settings.app_name.lower()})
        )
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otlp_endpoint, insecure=True))
        )
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app)
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
        log.info("tracing.enabled", endpoint=settings.otlp_endpoint)
    except Exception as exc:  # pragma: no cover - tracing is best-effort
        log.warning("tracing.setup_failed", error=str(exc))

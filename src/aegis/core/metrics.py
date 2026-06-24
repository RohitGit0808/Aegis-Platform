"""Prometheus metric definitions and exposition.

Centralising metric objects here prevents duplicate-registration errors and
gives the team a single catalogue of the platform's golden signals: request
rate/latency/errors plus domain metrics for runs and self-healing.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

# -- HTTP (RED method: Rate, Errors, Duration) ------------------------------- #
HTTP_REQUESTS = Counter(
    "aegis_http_requests_total",
    "Total HTTP requests.",
    labelnames=("method", "path", "status"),
)
HTTP_LATENCY = Histogram(
    "aegis_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    labelnames=("method", "path"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# -- Domain ------------------------------------------------------------------ #
RUNS_TOTAL = Counter("aegis_runs_total", "Test runs by terminal status.", labelnames=("status",))
RUN_DURATION = Histogram(
    "aegis_run_duration_seconds",
    "End-to-end test run duration in seconds.",
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300),
)
ACTIVE_RUNS = Gauge("aegis_active_runs", "Currently executing test runs.")

HEALING_ATTEMPTS = Counter(
    "aegis_healing_attempts_total",
    "Self-healing attempts by strategy and outcome.",
    labelnames=("strategy", "outcome"),
)
HEALING_CONFIDENCE = Histogram(
    "aegis_healing_confidence",
    "Confidence score of accepted healing proposals.",
    buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)

WORKER_TASKS = Counter(
    "aegis_worker_tasks_total",
    "Background worker task executions by outcome.",
    labelnames=("task", "outcome"),
)


def render_metrics() -> tuple[bytes, str]:
    """Return the Prometheus exposition payload and its content type."""
    return generate_latest(), CONTENT_TYPE_LATEST

# syntax=docker/dockerfile:1.7
# ============================================================================
# Aegis — production container image.
#
# Multi-stage build:
#   * Stage "builder" creates an isolated virtualenv and installs the project
#     (plus the optional `otel` extra for OpenTelemetry tracing) from
#     pyproject.toml via hatchling. Build tooling lives ONLY in this stage.
#   * Stage "runtime" is a lean python:3.13-slim image that copies the prebuilt
#     venv and application source, runs as an unprivileged user, and serves the
#     ASGI app with uvicorn.
#
# Build context is the repository root:
#   docker build -f docker/Dockerfile -t aegis:latest .
# (.dockerignore at the repo root keeps the context small.)
# ============================================================================

# ----------------------------------------------------------------------------
# Stage 1: builder — compile dependencies into a self-contained venv.
# ----------------------------------------------------------------------------
FROM python:3.13-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VENV_PATH=/opt/venv

# Build-time system deps. `build-essential` covers any sdist that needs a C
# compiler (e.g. transitive wheels without a manylinux build for this Python).
# These never make it into the runtime image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create the virtualenv up front and put it first on PATH so every subsequent
# `pip`/`python` invocation targets it.
RUN python -m venv "$VENV_PATH"
ENV PATH="$VENV_PATH/bin:$PATH"

RUN pip install --upgrade pip setuptools wheel

WORKDIR /app

# Copy only what hatchling needs to resolve and build the project. Copying the
# metadata + sources (rather than the whole context) keeps layer caching tight:
# dependency installs are re-run only when these inputs change.
# README.md is required by pyproject's `readme = "README.md"` for metadata.
COPY pyproject.toml README.md ./
COPY src ./src

# Install the project plus the OTLP exporter stack so tracing can be enabled
# purely via env (AEGIS_TRACING_ENABLED=true) without rebuilding.
RUN pip install ".[otel]"

# Migration assets are not part of the importable wheel, but the image must be
# able to run `alembic upgrade head` (CI, compose migrate service, k8s Job).
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations
COPY scripts ./scripts

# ----------------------------------------------------------------------------
# Stage 2: runtime — minimal image, no build tools, non-root.
# ----------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VENV_PATH=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    AEGIS_ENVIRONMENT=production

# `curl` is used by the container HEALTHCHECK to hit the liveness probe.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system appuser \
    && useradd --system --gid appuser --create-home --home-dir /home/appuser appuser

WORKDIR /app

# Bring over the fully-populated virtualenv and the application source. The
# package is installed in editable-equivalent form via the venv's site-packages
# entry pointing at /app/src, so the source must live at the same path.
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/src ./src
COPY --from=builder /app/pyproject.toml ./pyproject.toml
COPY --from=builder /app/README.md ./README.md
COPY --from=builder /app/alembic.ini ./alembic.ini
COPY --from=builder /app/migrations ./migrations
COPY --from=builder /app/scripts ./scripts

# Ensure the runtime user owns its working tree (e.g. for the default SQLite
# fallback file if Postgres is not configured).
RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Liveness probe — the app exposes GET /healthz (returns {"status":"alive"}).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail --silent http://localhost:8000/healthz || exit 1

# Serve the FastAPI ASGI app. Workers are tuned via env/compose; a single
# uvicorn process is the sane container default (scale horizontally instead).
CMD ["uvicorn", "aegis.main:app", "--host", "0.0.0.0", "--port", "8000"]

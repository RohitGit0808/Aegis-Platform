"""Application configuration via pydantic-settings (12-factor, env-driven).

A single cached :class:`Settings` instance is the source of truth for every
tunable in the platform. Settings are populated from environment variables
(prefixed ``AEGIS_``) and an optional ``.env`` file, in that order of
precedence. Sensible, *runnable* defaults are chosen so the platform boots with
zero external infrastructure (SQLite + in-process cache).
"""

from __future__ import annotations

import json
from enum import StrEnum
from functools import lru_cache
from typing import Any

from pydantic import Field, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_SECRET = "change-me-in-production-please-use-a-long-random-string"


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Strongly-typed, validated runtime configuration."""

    model_config = SettingsConfigDict(
        env_prefix="AEGIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # -- Application -------------------------------------------------------
    app_name: str = "Aegis"
    environment: Environment = Environment.LOCAL
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    # -- Logging -----------------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = False

    # -- Security ----------------------------------------------------------
    secret_key: str = _DEFAULT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 60 * 15
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 14

    # -- Persistence -------------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./aegis.db"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # -- Cache / queue -----------------------------------------------------
    # Empty string => use the in-process fake (FakeRedis), perfect for dev/tests.
    redis_url: str = ""

    # -- Self-healing engine ----------------------------------------------
    anthropic_api_key: str = ""
    healing_enabled: bool = True
    healing_model: str = "claude-opus-4-8"
    healing_min_confidence: float = 0.6
    healing_max_attempts: int = 3
    healing_llm_timeout_seconds: float = 20.0

    # -- Worker ------------------------------------------------------------
    worker_concurrency: int = 8
    run_max_retries: int = 2
    run_step_timeout_seconds: float = 30.0

    # -- Observability -----------------------------------------------------
    metrics_enabled: bool = True
    tracing_enabled: bool = False
    otlp_endpoint: str = "http://localhost:4317"

    # -- HTTP --------------------------------------------------------------
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # -- Rate limiting -----------------------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 120
    rate_limit_window_seconds: int = 60

    # ----------------------------------------------------------------------
    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors(cls, value: Any) -> Any:
        """Accept a JSON array or a comma-separated string for CORS origins."""
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return []
            if value.startswith("["):
                return json.loads(value)
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("healing_min_confidence")
    @classmethod
    def _check_confidence(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("healing_min_confidence must be within [0.0, 1.0]")
        return value

    @model_validator(mode="after")
    def _enforce_production_safety(self) -> Settings:
        """Fail fast on insecure or unsupported production configuration."""
        if self.environment is Environment.PRODUCTION:
            if self.secret_key == _DEFAULT_SECRET or len(self.secret_key) < 32:
                raise ValueError(
                    "AEGIS_SECRET_KEY must be a strong (>=32 char) non-default value in production."
                )
            if self.database_url.startswith("sqlite"):
                raise ValueError(
                    "SQLite is not supported in production; set a Postgres AEGIS_DATABASE_URL."
                )
        return self

    # -- Derived -----------------------------------------------------------
    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @computed_field  # type: ignore[prop-decorator]
    @property
    def use_fake_cache(self) -> bool:
        """True when no Redis URL is configured (use in-process FakeRedis)."""
        return not self.redis_url

    @computed_field  # type: ignore[prop-decorator]
    @property
    def healing_llm_available(self) -> bool:
        return self.healing_enabled and bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide, cached settings instance."""
    return Settings()


settings = get_settings()

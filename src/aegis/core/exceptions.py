"""Typed domain exceptions.

Services and repositories raise these provider-agnostic errors; a single set of
FastAPI exception handlers (``aegis.api.errors``) translates them into the
platform's structured error envelope. Keeping HTTP concerns out of the domain
keeps the core reusable from the CLI and workers too.
"""

from __future__ import annotations

from typing import Any


class AegisError(Exception):
    """Base class for all expected, mapped application errors."""

    http_status: int = 500
    code: str = "internal_error"
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details or {}
        super().__init__(self.message)


class NotFoundError(AegisError):
    http_status = 404
    code = "not_found"
    message = "The requested resource was not found."


class ConflictError(AegisError):
    http_status = 409
    code = "conflict"
    message = "The resource already exists or violates a uniqueness constraint."


class IdempotencyConflictError(ConflictError):
    code = "idempotency_conflict"
    message = "A different request already used this idempotency key."


class UnauthorizedError(AegisError):
    http_status = 401
    code = "unauthorized"
    message = "Authentication is required or has failed."


class ForbiddenError(AegisError):
    http_status = 403
    code = "forbidden"
    message = "You do not have permission to perform this action."


class DomainValidationError(AegisError):
    http_status = 422
    code = "validation_error"
    message = "The request is invalid."


class RateLimitedError(AegisError):
    http_status = 429
    code = "rate_limited"
    message = "Too many requests; please slow down."


class ServiceUnavailableError(AegisError):
    http_status = 503
    code = "service_unavailable"
    message = "A downstream dependency is unavailable."


class HealingError(AegisError):
    http_status = 502
    code = "healing_failed"
    message = "The self-healing engine could not produce a usable locator."

"""Structured application exceptions and consistent error payloads."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for expected, user-facing application errors."""

    status_code: int = 400
    code: str = "APP_ERROR"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        body: dict[str, Any] = {"error": {"code": self.code, "message": self.message}}
        if self.details:
            body["error"]["details"] = self.details
        return body


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"


class ValidationError(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"


class AuthError(AppError):
    status_code = 401
    code = "UNAUTHORIZED"


class ForbiddenError(AppError):
    status_code = 403
    code = "FORBIDDEN"


class RateLimitError(AppError):
    status_code = 429
    code = "RATE_LIMITED"


class ProviderError(AppError):
    """A downstream data provider failed. Callers should degrade gracefully."""

    status_code = 503
    code = "PROVIDER_UNAVAILABLE"


class ProviderTimeoutError(ProviderError):
    code = "PROVIDER_TIMEOUT"


class LLMUnavailableError(AppError):
    """Groq is unreachable/rate-limited. The product must still work."""

    status_code = 503
    code = "LLM_UNAVAILABLE"

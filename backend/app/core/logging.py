"""Structured logging.

Uses structlog so production logs are JSON (machine-readable on Render)
while local development stays human-readable.
"""

from __future__ import annotations

import logging
import sys

import structlog

from app.core.config import get_settings

_configured = False

# Keys whose values must never reach the logs.
_REDACT_KEYS = {
    "groq_api_key",
    "api_key",
    "password",
    "token",
    "access_token",
    "authorization",
    "secret",
    "jwt_secret",
    "mongodb_uri",
    "database_url",
}


def _redact(_logger: object, _name: str, event_dict: dict) -> dict:
    for k in list(event_dict.keys()):
        if k.lower() in _REDACT_KEYS:
            event_dict[k] = "***redacted***"
    return event_dict


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    # Third-party noise
    for noisy in ("yfinance", "peewee", "urllib3", "httpx", "httpcore", "pymongo"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact,
        structlog.processors.StackInfoRenderer(),
    ]
    if settings.is_production:
        processors.append(structlog.processors.format_exc_info)
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str = "app") -> structlog.BoundLogger:
    configure_logging()
    return structlog.get_logger(name)

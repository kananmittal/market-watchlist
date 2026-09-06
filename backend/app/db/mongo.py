"""MongoDB connection lifecycle.

Uses pymongo's native AsyncMongoClient (the supported successor to Motor).
A single client is shared process-wide: the driver pools connections, so
creating clients per request would be a scaling bug.
"""

from __future__ import annotations

from typing import Any

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import PyMongoError

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("db")

_client: AsyncMongoClient | None = None
_db: AsyncDatabase | None = None


class Collections:
    """Collection names in one place, so typos fail loudly at import."""

    USERS = "users"
    WATCHLISTS = "watchlists"
    MARKET_OBSERVATIONS = "market_observations"
    PRICE_HISTORY = "price_history"
    NEWS_EVENTS = "news_events"
    USER_SYMBOL_STATE = "user_symbol_state"
    ACTIVITY_EVENTS = "activity_events"
    CHANGE_EVENTS = "change_events"
    COPILOT_MESSAGES = "copilot_messages"


async def connect_to_mongo(uri: str | None = None, db_name: str | None = None) -> AsyncDatabase:
    """Open the shared client and verify the server is actually reachable."""
    global _client, _db
    settings = get_settings()
    uri = uri or settings.resolved_mongo_uri
    db_name = db_name or settings.mongodb_db

    _client = AsyncMongoClient(
        uri,
        serverSelectionTimeoutMS=8000,
        connectTimeoutMS=8000,
        retryWrites=True,
        tz_aware=True,  # critical: return timezone-aware datetimes
    )
    _db = _client[db_name]
    await _client.admin.command("ping")
    log.info("mongo_connected", database=db_name)
    return _db


async def close_mongo_connection() -> None:
    global _client, _db
    if _client is not None:
        await _client.close()
        log.info("mongo_disconnected")
    _client, _db = None, None


def get_db() -> AsyncDatabase:
    if _db is None:
        raise RuntimeError("Database not initialised. connect_to_mongo() must run first.")
    return _db


def get_client() -> AsyncMongoClient:
    if _client is None:
        raise RuntimeError("Database not initialised. connect_to_mongo() must run first.")
    return _client


async def ping() -> dict[str, Any]:
    """Health probe: never raises, always reports."""
    try:
        if _client is None:
            return {"ok": False, "error": "not_initialised"}
        res = await _client.admin.command("ping")
        return {"ok": bool(res.get("ok")), "database": get_settings().mongodb_db}
    except PyMongoError as exc:
        return {"ok": False, "error": type(exc).__name__}

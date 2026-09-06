"""Index definitions - this project's equivalent of migrations.

Idempotent: safe to run on every boot. Indexes are declared here rather
than scattered through repositories so the access patterns stay reviewable
in one place.
"""

from __future__ import annotations

from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.errors import OperationFailure

from app.core.logging import get_logger
from app.db.mongo import Collections, get_db

log = get_logger("db.indexes")

# Retain raw observations for 30 days; change events reference them but the
# product only ever compares against recent history.
OBSERVATION_TTL_SECONDS = 60 * 60 * 24 * 30
NEWS_TTL_SECONDS = 60 * 60 * 24 * 30
ACTIVITY_TTL_SECONDS = 60 * 60 * 24 * 180

INDEXES: dict[str, list[IndexModel]] = {
    Collections.USERS: [
        IndexModel([("email", ASCENDING)], unique=True, name="uniq_email"),
    ],
    Collections.WATCHLISTS: [
        IndexModel([("user_id", ASCENDING), ("created_at", ASCENDING)], name="user_created"),
        IndexModel([("user_id", ASCENDING), ("name", ASCENDING)], unique=True, name="uniq_user_name"),
        IndexModel([("user_id", ASCENDING), ("items.symbol", ASCENDING)], name="user_item_symbol"),
    ],
    Collections.MARKET_OBSERVATIONS: [
        # Primary read pattern: latest observation for a symbol.
        IndexModel([("symbol", ASCENDING), ("observed_at", DESCENDING)], name="symbol_observed"),
        # One row per symbol+source+timestamp; makes ingestion idempotent.
        IndexModel(
            [("symbol", ASCENDING), ("source", ASCENDING), ("observed_at", DESCENDING)],
            unique=True,
            name="uniq_symbol_source_observed",
        ),
        IndexModel(
            [("received_at", ASCENDING)], expireAfterSeconds=OBSERVATION_TTL_SECONDS, name="ttl_received"
        ),
    ],
    Collections.PRICE_HISTORY: [
        IndexModel(
            [("symbol", ASCENDING), ("interval", ASCENDING)], unique=True, name="uniq_symbol_interval"
        ),
        IndexModel([("fetched_at", ASCENDING)], name="fetched"),
    ],
    Collections.NEWS_EVENTS: [
        IndexModel([("symbol", ASCENDING), ("published_at", DESCENDING)], name="symbol_published"),
        # Deduplication guarantee: one row per underlying story per symbol.
        IndexModel([("dedupe_key", ASCENDING)], unique=True, name="uniq_dedupe"),
        IndexModel([("created_at", ASCENDING)], expireAfterSeconds=NEWS_TTL_SECONDS, name="ttl_created"),
    ],
    Collections.USER_SYMBOL_STATE: [
        IndexModel([("user_id", ASCENDING), ("symbol", ASCENDING)], unique=True, name="uniq_user_symbol"),
        IndexModel([("user_id", ASCENDING), ("last_viewed_at", DESCENDING)], name="user_last_viewed"),
    ],
    Collections.ACTIVITY_EVENTS: [
        IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="user_created"),
        IndexModel(
            [("user_id", ASCENDING), ("symbol", ASCENDING), ("created_at", DESCENDING)],
            name="user_symbol_created",
        ),
        IndexModel([("created_at", ASCENDING)], expireAfterSeconds=ACTIVITY_TTL_SECONDS, name="ttl_created"),
    ],
    Collections.CHANGE_EVENTS: [
        IndexModel([("user_id", ASCENDING), ("detected_at", DESCENDING)], name="user_detected"),
        IndexModel([("user_id", ASCENDING), ("status", ASCENDING)], name="user_status"),
        IndexModel(
            [("user_id", ASCENDING), ("symbol", ASCENDING), ("detected_at", DESCENDING)],
            name="user_symbol_detected",
        ),
        IndexModel([("id", ASCENDING)], unique=True, name="uniq_id"),
        IndexModel([("user_id", ASCENDING), ("attention_score", DESCENDING)], name="user_attention"),
    ],
    Collections.COPILOT_MESSAGES: [
        IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="user_created"),
    ],
}


async def ensure_indexes() -> dict[str, int]:
    """Create every declared index. Returns per-collection counts."""
    db = get_db()
    created: dict[str, int] = {}
    for name, models in INDEXES.items():
        try:
            await db[name].create_indexes(models)
            created[name] = len(models)
        except OperationFailure as exc:
            # An index changed shape between versions: log loudly, keep booting.
            log.warning("index_create_failed", collection=name, error=str(exc)[:200])
            created[name] = 0
    log.info("indexes_ensured", collections=len(created), total=sum(created.values()))
    return created

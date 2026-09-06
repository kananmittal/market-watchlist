"""Normalized news event persistence with dedupe-key uniqueness."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from pymongo import DESCENDING, UpdateOne
from pymongo.errors import BulkWriteError

from app.db.mongo import Collections, get_db
from app.models.domain import NewsEvent, utcnow


class NewsRepository:
    @property
    def col(self):
        return get_db()[Collections.NEWS_EVENTS]

    async def upsert_many(self, events: list[NewsEvent]) -> int:
        """Upsert on dedupe_key so three articles about one story stay one event."""
        if not events:
            return 0
        ops = []
        for e in events:
            doc = e.model_dump()
            doc["event_type"] = e.event_type.value
            ops.append(
                UpdateOne(
                    {"dedupe_key": e.dedupe_key},
                    {
                        "$set": {k: v for k, v in doc.items() if k != "article_count"},
                        "$max": {"article_count": e.article_count},
                    },
                    upsert=True,
                )
            )
        try:
            res = await self.col.bulk_write(ops, ordered=False)
            return (res.upserted_count or 0) + (res.modified_count or 0)
        except BulkWriteError:
            return 0

    async def for_symbol(self, symbol: str, *, since: Any = None, limit: int = 20) -> list[NewsEvent]:
        q: dict[str, Any] = {"symbol": symbol}
        if since is not None:
            q["published_at"] = {"$gte": since}
        cursor = self.col.find(q, {"_id": 0}).sort("published_at", DESCENDING).limit(limit)
        return [NewsEvent(**d) async for d in cursor]

    async def for_symbols(
        self, symbols: list[str], *, since: Any = None, per_symbol_limit: int = 5
    ) -> dict[str, list[NewsEvent]]:
        """Batch news for a whole watchlist in one query."""
        if not symbols:
            return {}
        q: dict[str, Any] = {"symbol": {"$in": symbols}}
        if since is not None:
            q["published_at"] = {"$gte": since}
        out: dict[str, list[NewsEvent]] = {s: [] for s in symbols}
        cursor = self.col.find(q, {"_id": 0}).sort("published_at", DESCENDING)
        async for d in cursor:
            bucket = out.setdefault(d["symbol"], [])
            if len(bucket) < per_symbol_limit:
                bucket.append(NewsEvent(**d))
        return out

    async def has_recent(self, symbol: str, *, minutes: int = 10) -> bool:
        """Cache probe: did we already fetch news for this symbol recently?"""
        doc = await self.col.find_one(
            {"symbol": symbol, "created_at": {"$gte": utcnow() - timedelta(minutes=minutes)}},
            {"_id": 1},
        )
        return doc is not None

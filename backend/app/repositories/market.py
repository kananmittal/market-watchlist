"""Global market observation + history persistence.

These rows are shared across ALL users. One fetch of TCS serves every user
watching TCS - this is the core scaling decision.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from pymongo import DESCENDING, UpdateOne
from pymongo.errors import BulkWriteError

from app.db.mongo import Collections, get_db
from app.models.domain import MarketObservation, OHLCBar, PriceHistory, utcnow


class MarketObservationRepository:
    @property
    def col(self):
        return get_db()[Collections.MARKET_OBSERVATIONS]

    async def save_many(self, observations: list[MarketObservation]) -> int:
        """Idempotent bulk upsert keyed on (symbol, source, observed_at)."""
        if not observations:
            return 0
        ops = []
        for o in observations:
            doc = o.model_dump()
            doc["quality"] = o.quality.value
            ops.append(
                UpdateOne(
                    {"symbol": o.symbol, "source": o.source, "observed_at": o.observed_at},
                    {"$set": doc},
                    upsert=True,
                )
            )
        try:
            res = await self.col.bulk_write(ops, ordered=False)
            return (res.upserted_count or 0) + (res.modified_count or 0)
        except BulkWriteError:
            return 0

    async def latest(self, symbol: str, *, source: str | None = None) -> MarketObservation | None:
        q: dict[str, Any] = {"symbol": symbol}
        if source:
            q["source"] = source
        doc = await self.col.find_one(q, {"_id": 0}, sort=[("observed_at", DESCENDING)])
        return MarketObservation(**doc) if doc else None

    async def latest_many(self, symbols: list[str]) -> dict[str, MarketObservation]:
        """Newest observation per symbol in ONE aggregation - no N+1."""
        if not symbols:
            return {}
        pipeline = [
            {"$match": {"symbol": {"$in": symbols}}},
            {"$sort": {"observed_at": DESCENDING}},
            {"$group": {"_id": "$symbol", "doc": {"$first": "$$ROOT"}}},
        ]
        out: dict[str, MarketObservation] = {}
        async for d in await self.col.aggregate(pipeline):
            doc = d["doc"]
            doc.pop("_id", None)
            out[doc["symbol"]] = MarketObservation(**doc)
        return out

    async def observation_at_or_before(self, symbol: str, when: Any) -> MarketObservation | None:
        """The baseline for 'since you last looked': what the price was then."""
        doc = await self.col.find_one(
            {"symbol": symbol, "observed_at": {"$lte": when}},
            {"_id": 0},
            sort=[("observed_at", DESCENDING)],
        )
        return MarketObservation(**doc) if doc else None

    async def observations_at_or_before_many(
        self, symbols: list[str], when: Any
    ) -> dict[str, MarketObservation]:
        if not symbols:
            return {}
        pipeline = [
            {"$match": {"symbol": {"$in": symbols}, "observed_at": {"$lte": when}}},
            {"$sort": {"observed_at": DESCENDING}},
            {"$group": {"_id": "$symbol", "doc": {"$first": "$$ROOT"}}},
        ]
        out: dict[str, MarketObservation] = {}
        async for d in await self.col.aggregate(pipeline):
            doc = d["doc"]
            doc.pop("_id", None)
            out[doc["symbol"]] = MarketObservation(**doc)
        return out

    async def sources_for(self, symbol: str, *, within_seconds: int = 300) -> list[MarketObservation]:
        """Recent observations from every source - used for conflict detection."""
        since = utcnow() - timedelta(seconds=within_seconds)
        cursor = self.col.find({"symbol": symbol, "observed_at": {"$gte": since}}, {"_id": 0})
        return [MarketObservation(**d) async for d in cursor]


class PriceHistoryRepository:
    """Historical bars are long-lived and expensive to fetch: cache them."""

    @property
    def col(self):
        return get_db()[Collections.PRICE_HISTORY]

    async def save(self, history: PriceHistory, interval: str = "1d") -> None:
        await self.col.update_one(
            {"symbol": history.symbol, "interval": interval},
            {
                "$set": {
                    "symbol": history.symbol,
                    "interval": interval,
                    "source": history.source,
                    "is_synthetic": history.is_synthetic,
                    "fetched_at": history.fetched_at,
                    "bars": [b.model_dump() for b in history.bars],
                }
            },
            upsert=True,
        )

    async def get(
        self, symbol: str, interval: str = "1d", max_age_seconds: int | None = None
    ) -> PriceHistory | None:
        doc = await self.col.find_one({"symbol": symbol, "interval": interval}, {"_id": 0})
        if not doc:
            return None
        if max_age_seconds is not None:
            fetched = doc.get("fetched_at")
            if fetched and (utcnow() - fetched).total_seconds() > max_age_seconds:
                return None
        return PriceHistory(
            symbol=doc["symbol"],
            bars=[OHLCBar(**b) for b in doc.get("bars", [])],
            source=doc.get("source", "unknown"),
            fetched_at=doc.get("fetched_at", utcnow()),
            is_synthetic=doc.get("is_synthetic", False),
        )

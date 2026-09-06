"""User + per-user symbol state + activity log persistence."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from pymongo import DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.errors import ConflictError
from app.db.mongo import Collections, get_db
from app.models.domain import ActivityEvent, User, UserSymbolState, utcnow
from app.models.enums import ActivityType


def _strip(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if doc is None:
        return None
    doc.pop("_id", None)
    return doc


class UserRepository:
    @property
    def col(self):
        return get_db()[Collections.USERS]

    async def create(
        self, *, email: str, display_name: str, password_hash: str | None, is_demo: bool = False
    ) -> User:
        user = User(
            id=f"usr_{uuid.uuid4().hex[:16]}",
            email=email.strip().lower(),
            display_name=display_name.strip(),
            password_hash=password_hash,
            is_demo=is_demo,
        )
        try:
            await self.col.insert_one(user.model_dump())
        except DuplicateKeyError as exc:
            raise ConflictError("An account with this email already exists.") from exc
        return user

    async def get_by_email(self, email: str) -> User | None:
        doc = _strip(await self.col.find_one({"email": email.strip().lower()}))
        return User(**doc) if doc else None

    async def get_by_id(self, user_id: str) -> User | None:
        doc = _strip(await self.col.find_one({"id": user_id}))
        return User(**doc) if doc else None

    async def touch_active(self, user_id: str) -> None:
        await self.col.update_one({"id": user_id}, {"$set": {"last_active_at": utcnow()}})

    async def get_and_set_dashboard_view(self, user_id: str) -> datetime | None:
        """Atomically read the previous dashboard-view time and stamp a new one.

        Returning the PREVIOUS value is the whole point: it is the anchor for
        "since you last looked". Uses find_one_and_update so two concurrent
        loads cannot both claim to be the first.
        """
        doc = await self.col.find_one_and_update(
            {"id": user_id},
            {"$set": {"last_dashboard_view_at": utcnow()}},
            projection={"last_dashboard_view_at": 1, "_id": 0},
            return_document=ReturnDocument.BEFORE,
        )
        return doc.get("last_dashboard_view_at") if doc else None


class UserSymbolStateRepository:
    @property
    def col(self):
        return get_db()[Collections.USER_SYMBOL_STATE]

    async def get(self, user_id: str, symbol: str) -> UserSymbolState | None:
        doc = _strip(await self.col.find_one({"user_id": user_id, "symbol": symbol}))
        return UserSymbolState(**doc) if doc else None

    async def get_many(self, user_id: str, symbols: list[str]) -> dict[str, UserSymbolState]:
        """Batch fetch - avoids one query per watchlist symbol (N+1)."""
        if not symbols:
            return {}
        cursor = self.col.find({"user_id": user_id, "symbol": {"$in": symbols}})
        out: dict[str, UserSymbolState] = {}
        async for doc in cursor:
            _strip(doc)
            out[doc["symbol"]] = UserSymbolState(**doc)
        return out

    async def ensure(self, user_id: str, symbol: str) -> UserSymbolState:
        now = utcnow()
        doc = await self.col.find_one_and_update(
            {"user_id": user_id, "symbol": symbol},
            {
                "$setOnInsert": {
                    "user_id": user_id,
                    "symbol": symbol,
                    "first_added_at": now,
                    "last_viewed_at": None,
                    "last_acknowledged_at": None,
                    "view_count": 0,
                    "interest_score": 0.0,
                }
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0},
        )
        return UserSymbolState(**doc)

    async def mark_viewed(self, user_id: str, symbol: str) -> UserSymbolState:
        """Viewing is NOT acknowledgement - only last_viewed_at moves."""
        doc = await self.col.find_one_and_update(
            {"user_id": user_id, "symbol": symbol},
            {
                "$set": {"last_viewed_at": utcnow()},
                "$inc": {"view_count": 1},
                "$setOnInsert": {
                    "user_id": user_id,
                    "symbol": symbol,
                    "first_added_at": utcnow(),
                    "last_acknowledged_at": None,
                    "interest_score": 0.0,
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0},
        )
        return UserSymbolState(**doc)

    async def mark_acknowledged(self, user_id: str, symbol: str) -> UserSymbolState:
        """Record an explicit review.

        Deliberately does NOT touch last_viewed_at. That timestamp is the
        "since you last looked" anchor; moving it here would reset the
        comparison window, so the change the user just reviewed would be
        recomputed as a zero-percent move and vanish from the feed instead of
        showing as reviewed.
        """
        doc = await self.col.find_one_and_update(
            {"user_id": user_id, "symbol": symbol},
            {
                "$set": {"last_acknowledged_at": utcnow()},
                "$setOnInsert": {
                    "user_id": user_id,
                    "symbol": symbol,
                    "first_added_at": utcnow(),
                    "view_count": 0,
                    "interest_score": 0.0,
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0},
        )
        return UserSymbolState(**doc)

    async def set_interest(self, user_id: str, symbol: str, score: float) -> None:
        await self.col.update_one(
            {"user_id": user_id, "symbol": symbol},
            {"$set": {"interest_score": round(max(0.0, min(1.0, score)), 4)}},
        )

    async def delete(self, user_id: str, symbol: str) -> None:
        await self.col.delete_one({"user_id": user_id, "symbol": symbol})


class ActivityRepository:
    @property
    def col(self):
        return get_db()[Collections.ACTIVITY_EVENTS]

    async def log(
        self,
        user_id: str,
        event_type: ActivityType,
        *,
        symbol: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ActivityEvent:
        ev = ActivityEvent(user_id=user_id, event_type=event_type, symbol=symbol, metadata=metadata or {})
        payload = ev.model_dump()
        payload["event_type"] = ev.event_type.value
        await self.col.insert_one(payload)
        return ev

    async def recent(
        self, user_id: str, *, symbol: str | None = None, limit: int = 50
    ) -> list[ActivityEvent]:
        q: dict[str, Any] = {"user_id": user_id}
        if symbol:
            q["symbol"] = symbol
        cursor = self.col.find(q, {"_id": 0}).sort("created_at", DESCENDING).limit(limit)
        return [ActivityEvent(**doc) async for doc in cursor]

    async def counts_by_symbol(self, user_id: str, *, days: int = 30) -> dict[str, int]:
        """Aggregate view counts per symbol in one round trip (feeds interest score)."""
        since = utcnow() - timedelta(days=days)
        pipeline = [
            {"$match": {"user_id": user_id, "created_at": {"$gte": since}, "symbol": {"$ne": None}}},
            {"$group": {"_id": "$symbol", "n": {"$sum": 1}}},
        ]
        return {d["_id"]: d["n"] async for d in await self.col.aggregate(pipeline)}

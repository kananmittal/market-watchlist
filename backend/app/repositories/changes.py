"""ChangeEvent persistence - per-user product interpretation."""

from __future__ import annotations

from typing import Any

from pymongo import DESCENDING, UpdateOne
from pymongo.errors import BulkWriteError

from app.core.errors import NotFoundError
from app.db.mongo import Collections, get_db
from app.models.domain import ChangeEvent, utcnow
from app.models.enums import ChangeStatus, ChangeType


def _dump(c: ChangeEvent) -> dict[str, Any]:
    d = c.model_dump()
    d["change_type"] = c.change_type.value
    d["severity"] = c.severity.value
    d["status"] = c.status.value
    d["primary_reason"] = c.primary_reason.value
    d["data_quality"] = c.data_quality.value
    d["evidence"] = [{**e.model_dump(), "evidence_type": e.evidence_type.value} for e in c.evidence]
    return d


class ChangeEventRepository:
    @property
    def col(self):
        return get_db()[Collections.CHANGE_EVENTS]

    async def upsert_many(self, events: list[ChangeEvent]) -> int:
        """Replace the current change event per (user, symbol, since-anchor).

        Recomputing the dashboard must not create duplicate cards, but it must
        also never silently reset a status the user already moved forward.
        """
        if not events:
            return 0
        ops = []
        for e in events:
            doc = _dump(e)
            preserved = {k: v for k, v in doc.items() if k != "status"}
            ops.append(
                UpdateOne(
                    {"user_id": e.user_id, "symbol": e.symbol, "since": e.since},
                    {"$set": preserved, "$setOnInsert": {"status": doc["status"]}},
                    upsert=True,
                )
            )
        try:
            res = await self.col.bulk_write(ops, ordered=False)
            return (res.upserted_count or 0) + (res.modified_count or 0)
        except BulkWriteError:
            return 0

    async def get(self, user_id: str, change_id: str) -> ChangeEvent:
        doc = await self.col.find_one({"id": change_id, "user_id": user_id}, {"_id": 0})
        if not doc:
            raise NotFoundError("Change not found.")
        return ChangeEvent(**doc)

    async def list_for_user(
        self,
        user_id: str,
        *,
        statuses: list[str] | None = None,
        symbol: str | None = None,
        severity: str | None = None,
        limit: int = 100,
    ) -> list[ChangeEvent]:
        q: dict[str, Any] = {"user_id": user_id}
        if statuses:
            q["status"] = {"$in": statuses}
        if symbol:
            q["symbol"] = symbol
        if severity:
            q["severity"] = severity
        cursor = (
            self.col.find(q, {"_id": 0})
            .sort([("attention_score", DESCENDING), ("detected_at", DESCENDING)])
            .limit(limit)
        )
        return [ChangeEvent(**d) async for d in cursor]

    async def set_status(self, user_id: str, change_id: str, status: ChangeStatus) -> ChangeEvent:
        res = await self.col.update_one(
            {"id": change_id, "user_id": user_id},
            {"$set": {"status": status.value, "updated_at": utcnow()}},
        )
        if res.matched_count == 0:
            raise NotFoundError("Change not found.")
        return await self.get(user_id, change_id)

    async def mark_symbol_viewed(self, user_id: str, symbol: str) -> None:
        """Opening a stock advances NEW/IMPORTANT to VIEWED - but never to ACKNOWLEDGED."""
        await self.col.update_many(
            {
                "user_id": user_id,
                "symbol": symbol,
                "status": {"$in": [ChangeStatus.NEW.value, ChangeStatus.IMPORTANT.value]},
            },
            {"$set": {"status": ChangeStatus.VIEWED.value, "updated_at": utcnow()}},
        )

    async def unreviewed_count(self, user_id: str) -> int:
        """Only MATERIAL changes can be unreviewed. A quiet stock is not a task."""
        return await self.col.count_documents(
            {
                "user_id": user_id,
                "change_type": {"$ne": ChangeType.NO_MATERIAL_CHANGE.value},
                "status": {
                    "$in": [ChangeStatus.NEW.value, ChangeStatus.IMPORTANT.value, ChangeStatus.VIEWED.value]
                },
            }
        )

    async def delete_for_symbol(self, user_id: str, symbol: str) -> None:
        await self.col.delete_many({"user_id": user_id, "symbol": symbol})

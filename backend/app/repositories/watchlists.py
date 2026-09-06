"""Watchlist persistence.

Items are embedded in the watchlist document: they are always read with
their parent, are bounded in number, and embedding avoids a join per view.
"""

from __future__ import annotations

import uuid
from typing import Any

from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

from app.core.errors import ConflictError, NotFoundError
from app.db.mongo import Collections, get_db
from app.models.domain import Watchlist, WatchlistItem, utcnow

MAX_ITEMS_PER_WATCHLIST = 50


class WatchlistRepository:
    @property
    def col(self):
        return get_db()[Collections.WATCHLISTS]

    async def create(self, user_id: str, name: str) -> Watchlist:
        wl = Watchlist(id=f"wl_{uuid.uuid4().hex[:16]}", user_id=user_id, name=name.strip())
        try:
            await self.col.insert_one(wl.model_dump())
        except DuplicateKeyError as exc:
            raise ConflictError(f"You already have a watchlist named '{name}'.") from exc
        return wl

    async def list_for_user(self, user_id: str) -> list[Watchlist]:
        cursor = self.col.find({"user_id": user_id}, {"_id": 0}).sort("created_at", ASCENDING)
        return [Watchlist(**doc) async for doc in cursor]

    async def get(self, user_id: str, watchlist_id: str) -> Watchlist:
        doc = await self.col.find_one({"id": watchlist_id, "user_id": user_id}, {"_id": 0})
        if not doc:
            raise NotFoundError("Watchlist not found.")
        return Watchlist(**doc)

    async def rename(self, user_id: str, watchlist_id: str, name: str) -> Watchlist:
        try:
            res = await self.col.update_one(
                {"id": watchlist_id, "user_id": user_id},
                {"$set": {"name": name.strip(), "updated_at": utcnow()}},
            )
        except DuplicateKeyError as exc:
            raise ConflictError(f"You already have a watchlist named '{name}'.") from exc
        if res.matched_count == 0:
            raise NotFoundError("Watchlist not found.")
        return await self.get(user_id, watchlist_id)

    async def delete(self, user_id: str, watchlist_id: str) -> None:
        res = await self.col.delete_one({"id": watchlist_id, "user_id": user_id})
        if res.deleted_count == 0:
            raise NotFoundError("Watchlist not found.")

    async def add_item(
        self, user_id: str, watchlist_id: str, symbol: str, display_name: str | None = None
    ) -> Watchlist:
        wl = await self.get(user_id, watchlist_id)
        symbol = symbol.strip().upper()
        if any(i.symbol == symbol for i in wl.items):
            raise ConflictError(f"{symbol} is already in this watchlist.")
        if len(wl.items) >= MAX_ITEMS_PER_WATCHLIST:
            raise ConflictError(f"A watchlist can hold at most {MAX_ITEMS_PER_WATCHLIST} symbols.")

        item = WatchlistItem(
            symbol=symbol,
            display_name=display_name or symbol,
            sort_order=max((i.sort_order for i in wl.items), default=-1) + 1,
        )
        await self.col.update_one(
            {"id": watchlist_id, "user_id": user_id},
            {"$push": {"items": item.model_dump()}, "$set": {"updated_at": utcnow()}},
        )
        return await self.get(user_id, watchlist_id)

    async def remove_item(self, user_id: str, watchlist_id: str, symbol: str) -> Watchlist:
        symbol = symbol.strip().upper()
        res = await self.col.update_one(
            {"id": watchlist_id, "user_id": user_id},
            {"$pull": {"items": {"symbol": symbol}}, "$set": {"updated_at": utcnow()}},
        )
        if res.matched_count == 0:
            raise NotFoundError("Watchlist not found.")
        if res.modified_count == 0:
            raise NotFoundError(f"{symbol} is not in this watchlist.")
        return await self.get(user_id, watchlist_id)

    async def reorder(self, user_id: str, watchlist_id: str, symbols: list[str]) -> Watchlist:
        wl = await self.get(user_id, watchlist_id)
        order = {s.strip().upper(): i for i, s in enumerate(symbols)}
        items = sorted(wl.items, key=lambda it: order.get(it.symbol, 10_000))
        for i, it in enumerate(items):
            it.sort_order = i
        await self.col.update_one(
            {"id": watchlist_id, "user_id": user_id},
            {"$set": {"items": [i.model_dump() for i in items], "updated_at": utcnow()}},
        )
        return await self.get(user_id, watchlist_id)

    async def all_symbols_for_user(self, user_id: str) -> list[str]:
        """Every distinct symbol across a user's watchlists - one query, for batching."""
        pipeline: list[dict[str, Any]] = [
            {"$match": {"user_id": user_id}},
            {"$unwind": "$items"},
            {"$group": {"_id": "$items.symbol"}},
            {"$sort": {"_id": 1}},
        ]
        return [d["_id"] async for d in await self.col.aggregate(pipeline)]

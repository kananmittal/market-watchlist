"""Watchlist management."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_memory_service
from app.api.mappers import watchlist_to_response
from app.api.schemas import (
    AddItemRequest,
    CreateWatchlistRequest,
    RenameWatchlistRequest,
    ReorderRequest,
    WatchlistResponse,
)
from app.models.domain import User
from app.models.enums import ActivityType
from app.providers.symbols import display_name
from app.repositories.watchlists import WatchlistRepository
from app.services.user_memory import UserMemoryService

router = APIRouter(prefix="/watchlists", tags=["watchlists"])


@router.get("", response_model=list[WatchlistResponse])
async def list_watchlists(user: User = Depends(get_current_user)) -> list[WatchlistResponse]:
    return [watchlist_to_response(w) for w in await WatchlistRepository().list_for_user(user.id)]


@router.post("", response_model=WatchlistResponse, status_code=201)
async def create_watchlist(
    body: CreateWatchlistRequest,
    user: User = Depends(get_current_user),
    memory: UserMemoryService = Depends(get_memory_service),
) -> WatchlistResponse:
    wl = await WatchlistRepository().create(user.id, body.name)
    await memory.log(
        user.id, ActivityType.WATCHLIST_CREATED, metadata={"watchlist_id": wl.id, "name": wl.name}
    )
    return watchlist_to_response(wl)


@router.get("/{watchlist_id}", response_model=WatchlistResponse)
async def get_watchlist(watchlist_id: str, user: User = Depends(get_current_user)) -> WatchlistResponse:
    return watchlist_to_response(await WatchlistRepository().get(user.id, watchlist_id))


@router.patch("/{watchlist_id}", response_model=WatchlistResponse)
async def rename_watchlist(
    watchlist_id: str,
    body: RenameWatchlistRequest,
    user: User = Depends(get_current_user),
    memory: UserMemoryService = Depends(get_memory_service),
) -> WatchlistResponse:
    wl = await WatchlistRepository().rename(user.id, watchlist_id, body.name)
    await memory.log(
        user.id, ActivityType.WATCHLIST_RENAMED, metadata={"watchlist_id": watchlist_id, "name": body.name}
    )
    return watchlist_to_response(wl)


@router.delete("/{watchlist_id}", status_code=204)
async def delete_watchlist(
    watchlist_id: str,
    user: User = Depends(get_current_user),
    memory: UserMemoryService = Depends(get_memory_service),
) -> None:
    await WatchlistRepository().delete(user.id, watchlist_id)
    await memory.log(user.id, ActivityType.WATCHLIST_DELETED, metadata={"watchlist_id": watchlist_id})


@router.post("/{watchlist_id}/items", response_model=WatchlistResponse, status_code=201)
async def add_item(
    watchlist_id: str,
    body: AddItemRequest,
    user: User = Depends(get_current_user),
    memory: UserMemoryService = Depends(get_memory_service),
) -> WatchlistResponse:
    wl = await WatchlistRepository().add_item(user.id, watchlist_id, body.symbol, display_name(body.symbol))
    # Create the per-user state now so "since you last looked" anchors to when
    # the symbol was added rather than to a drifting dashboard timestamp.
    await memory.ensure_tracked(user.id, body.symbol)
    await memory.log(
        user.id, ActivityType.STOCK_ADDED, symbol=body.symbol, metadata={"watchlist_id": watchlist_id}
    )
    return watchlist_to_response(wl)


@router.delete("/{watchlist_id}/items/{symbol}", response_model=WatchlistResponse)
async def remove_item(
    watchlist_id: str,
    symbol: str,
    user: User = Depends(get_current_user),
    memory: UserMemoryService = Depends(get_memory_service),
) -> WatchlistResponse:
    wl = await WatchlistRepository().remove_item(user.id, watchlist_id, symbol)
    await memory.log(
        user.id, ActivityType.STOCK_REMOVED, symbol=symbol.upper(), metadata={"watchlist_id": watchlist_id}
    )
    # Drop this user's state for the symbol only if no other watchlist holds it.
    remaining = await WatchlistRepository().all_symbols_for_user(user.id)
    if symbol.strip().upper() not in remaining:
        await memory.forget_symbol(user.id, symbol)
    return watchlist_to_response(wl)


@router.post("/{watchlist_id}/reorder", response_model=WatchlistResponse)
async def reorder(
    watchlist_id: str, body: ReorderRequest, user: User = Depends(get_current_user)
) -> WatchlistResponse:
    return watchlist_to_response(await WatchlistRepository().reorder(user.id, watchlist_id, body.symbols))

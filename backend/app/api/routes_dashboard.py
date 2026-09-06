"""Dashboard, change feed and stock detail - the core product surface."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    get_current_user,
    get_dashboard_service,
    get_market_service,
    get_memory_service,
)
from app.api.mappers import (
    activity_to_response,
    change_to_response,
    history_to_response,
    market_to_response,
    news_to_response,
    quote_to_response,
)
from app.api.schemas import (
    CatchUpResponse,
    ChangeResponse,
    DashboardResponse,
    StockDetailResponse,
    WatchlistRowResponse,
)
from app.core.errors import NotFoundError
from app.core.market_time import get_market_state
from app.models.domain import User
from app.models.enums import ActivityType, ChangeStatus
from app.providers.symbols import BENCHMARK_SYMBOL, display_name, sector_index_for, sector_of
from app.repositories.changes import ChangeEventRepository
from app.repositories.news import NewsRepository
from app.services.dashboard import DashboardService
from app.services.market_data import MarketDataService
from app.services.user_memory import UserMemoryService

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    advance_anchor: bool = Query(default=True),
    include_news: bool = Query(default=True),
    user: User = Depends(get_current_user),
    dashboard: DashboardService = Depends(get_dashboard_service),
    market: MarketDataService = Depends(get_market_service),
) -> DashboardResponse:
    """The "since you last looked" view.

    advance_anchor=false lets the UI poll without moving the reference point.
    """
    result = await dashboard.build(user.id, advance_anchor=advance_anchor, include_news=include_news)
    return DashboardResponse(
        last_checked_at=result.last_checked_at,
        away_for=result.away_for,
        is_first_visit=result.is_first_visit,
        demo_mode=result.demo_mode,
        market=market_to_response(result.market),
        benchmark=quote_to_response(result.benchmark, market.describe_freshness(result.benchmark)),
        catch_up=CatchUpResponse(**dashboard.catch_me_up(result)),
        meaningful_changes=[change_to_response(c) for c in result.meaningful_changes],
        normal_movements=[change_to_response(c) for c in result.normal_movements],
        watchlist=[
            WatchlistRowResponse(
                symbol=v.symbol,
                name=v.name,
                quote=quote_to_response(v.observation, v.freshness),
                change=change_to_response(v.change),
                news=[news_to_response(n) for n in v.news],
                last_viewed_at=v.last_viewed_at,
                last_acknowledged_at=v.last_acknowledged_at,
            )
            for v in result.symbols
        ],
    )


@router.get("/changes", response_model=list[ChangeResponse])
async def list_changes(
    status: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    user: User = Depends(get_current_user),
) -> list[ChangeResponse]:
    statuses = [s.strip().upper() for s in status.split(",")] if status else None
    changes = await ChangeEventRepository().list_for_user(
        user.id,
        statuses=statuses,
        symbol=symbol.strip().upper() if symbol else None,
        severity=severity.strip().upper() if severity else None,
        limit=limit,
    )
    return [change_to_response(c) for c in changes]


@router.get("/changes/{change_id}", response_model=ChangeResponse)
async def get_change(
    change_id: str,
    user: User = Depends(get_current_user),
    memory: UserMemoryService = Depends(get_memory_service),
) -> ChangeResponse:
    change = await ChangeEventRepository().get(user.id, change_id)
    await memory.log(
        user.id, ActivityType.CHANGE_VIEWED, symbol=change.symbol, metadata={"change_id": change_id}
    )
    return change_to_response(change)


@router.post("/changes/{change_id}/acknowledge", response_model=ChangeResponse)
async def acknowledge_change(
    change_id: str,
    user: User = Depends(get_current_user),
    memory: UserMemoryService = Depends(get_memory_service),
) -> ChangeResponse:
    """Explicit review. Distinct from merely viewing the stock."""
    repo = ChangeEventRepository()
    change = await repo.get(user.id, change_id)
    updated = await repo.set_status(user.id, change_id, ChangeStatus.ACKNOWLEDGED)
    await memory.acknowledge(user.id, change.symbol)
    return change_to_response(updated)


@router.post("/changes/{change_id}/dismiss", response_model=ChangeResponse)
async def dismiss_change(
    change_id: str,
    user: User = Depends(get_current_user),
    memory: UserMemoryService = Depends(get_memory_service),
) -> ChangeResponse:
    repo = ChangeEventRepository()
    change = await repo.get(user.id, change_id)
    updated = await repo.set_status(user.id, change_id, ChangeStatus.DISMISSED)
    await memory.log(
        user.id, ActivityType.CHANGE_DISMISSED, symbol=change.symbol, metadata={"change_id": change_id}
    )
    return change_to_response(updated)


@router.get("/stocks/{symbol}", response_model=StockDetailResponse)
async def get_stock_detail(
    symbol: str,
    period: str = Query(default="3mo"),
    user: User = Depends(get_current_user),
    market: MarketDataService = Depends(get_market_service),
    memory: UserMemoryService = Depends(get_memory_service),
) -> StockDetailResponse:
    """Stock detail. Viewing records last_viewed_at but never acknowledges."""
    symbol = symbol.strip().upper()
    state = await memory.record_view(user.id, symbol)

    sector_pair = sector_index_for(symbol)
    wanted = [symbol, BENCHMARK_SYMBOL] + ([sector_pair[1]] if sector_pair else [])
    quotes = await market.get_quotes(wanted)
    observation = quotes.get(symbol)
    if observation is None:
        raise NotFoundError(f"No market data available for {symbol}.")

    history = await market.get_history(
        symbol, period=period if period in {"1mo", "3mo", "6mo", "1y"} else "3mo"
    )
    news = await NewsRepository().for_symbol(symbol, limit=8)
    activity = await memory.recent_activity(user.id, symbol=symbol, limit=25)
    recent = await ChangeEventRepository().list_for_user(user.id, symbol=symbol, limit=1)
    change = recent[0] if recent else None

    return StockDetailResponse(
        symbol=symbol,
        name=display_name(symbol),
        sector=sector_of(symbol),
        quote=quote_to_response(observation, market.describe_freshness(observation)),
        change=change_to_response(change),
        benchmark=quote_to_response(quotes.get(BENCHMARK_SYMBOL)),
        sector_index=quote_to_response(quotes.get(sector_pair[1])) if sector_pair else None,
        history=history_to_response(history),
        news=[news_to_response(n) for n in news],
        activity=[activity_to_response(a) for a in activity],
        last_viewed_at=state.last_viewed_at,
        last_acknowledged_at=state.last_acknowledged_at,
    )


@router.post("/stocks/{symbol}/acknowledge", response_model=StockDetailResponse)
async def acknowledge_stock(
    symbol: str,
    user: User = Depends(get_current_user),
    market: MarketDataService = Depends(get_market_service),
    memory: UserMemoryService = Depends(get_memory_service),
) -> StockDetailResponse:
    """Mark every current change for a symbol as reviewed."""
    symbol = symbol.strip().upper()
    await memory.acknowledge(user.id, symbol)
    repo = ChangeEventRepository()
    for change in await repo.list_for_user(user.id, symbol=symbol, limit=20):
        if change.status not in {ChangeStatus.ACKNOWLEDGED, ChangeStatus.DISMISSED}:
            await repo.set_status(user.id, change.id, ChangeStatus.ACKNOWLEDGED)
    return await get_stock_detail(symbol, "3mo", user, market, memory)


@router.get("/market-status")
async def market_status() -> dict:
    return market_to_response(get_market_state()).model_dump()

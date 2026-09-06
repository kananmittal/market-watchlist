"""Market data: search, quotes, history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user, get_market_service, get_memory_service
from app.api.mappers import history_to_response, quote_to_response
from app.api.schemas import HistoryResponse, QuoteResponse, SymbolSearchResult
from app.core.errors import NotFoundError
from app.models.domain import User
from app.models.enums import ActivityType
from app.providers.symbols import search as symbol_search
from app.services.market_data import MarketDataService
from app.services.user_memory import UserMemoryService

router = APIRouter(prefix="/market", tags=["market"])

ALLOWED_PERIODS = {"1mo", "3mo", "6mo", "1y"}


@router.get("/search", response_model=list[SymbolSearchResult])
async def search_symbols(
    q: str = Query(min_length=1, max_length=40),
    limit: int = Query(default=10, ge=1, le=25),
    user: User = Depends(get_current_user),
    memory: UserMemoryService = Depends(get_memory_service),
) -> list[SymbolSearchResult]:
    results = symbol_search(q, limit=limit)
    if results:
        await memory.log(user.id, ActivityType.STOCK_SEARCHED, metadata={"query": q})
    return [
        SymbolSearchResult(symbol=r.symbol, name=r.name, sector=r.sector, is_index=r.is_index)
        for r in results
    ]


@router.get("/quote/{symbol}", response_model=QuoteResponse)
async def get_quote(
    symbol: str,
    market: MarketDataService = Depends(get_market_service),
    _: User = Depends(get_current_user),
) -> QuoteResponse:
    obs = await market.get_quote(symbol)
    if obs is None:
        raise NotFoundError(f"No market data available for {symbol.upper()}.")
    return quote_to_response(obs, market.describe_freshness(obs))


@router.get("/history/{symbol}", response_model=HistoryResponse)
async def get_history(
    symbol: str,
    period: str = Query(default="3mo"),
    market: MarketDataService = Depends(get_market_service),
    user: User = Depends(get_current_user),
    memory: UserMemoryService = Depends(get_memory_service),
) -> HistoryResponse:
    if period not in ALLOWED_PERIODS:
        period = "3mo"
    history = await market.get_history(symbol, period=period)
    if history is None:
        raise NotFoundError(f"No historical data available for {symbol.upper()}.")
    await memory.log(
        user.id, ActivityType.CHART_VIEWED, symbol=symbol.strip().upper(), metadata={"period": period}
    )
    return history_to_response(history)

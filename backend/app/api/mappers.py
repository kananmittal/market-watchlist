"""Domain -> API response mapping, kept out of the routers.

The mappers are overloaded: passing a value returns a response, passing None
returns None. Without this the routers would appear to return Optional even
where the domain object is known to exist.
"""

from __future__ import annotations

from typing import overload

from app.api.schemas import (
    ActivityResponse,
    ChangeMetricsResponse,
    ChangeResponse,
    EvidenceResponse,
    HistoryBar,
    HistoryResponse,
    MarketStatusResponse,
    NewsResponse,
    QuoteResponse,
    ScoreBreakdownResponse,
    UserResponse,
    WatchlistItemResponse,
    WatchlistResponse,
)
from app.core.market_time import MarketState
from app.models.domain import (
    ActivityEvent,
    ChangeEvent,
    MarketObservation,
    NewsEvent,
    PriceHistory,
    User,
    Watchlist,
)
from app.providers.symbols import display_name


def user_to_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_demo=user.is_demo,
        created_at=user.created_at,
        last_dashboard_view_at=user.last_dashboard_view_at,
    )


def watchlist_to_response(wl: Watchlist) -> WatchlistResponse:
    return WatchlistResponse(
        id=wl.id,
        name=wl.name,
        created_at=wl.created_at,
        updated_at=wl.updated_at,
        items=[
            WatchlistItemResponse(
                symbol=i.symbol,
                display_name=i.display_name or display_name(i.symbol),
                added_at=i.added_at,
                sort_order=i.sort_order,
            )
            for i in sorted(wl.items, key=lambda x: x.sort_order)
        ],
    )


@overload
def quote_to_response(obs: MarketObservation, freshness: dict | None = ...) -> QuoteResponse: ...
@overload
def quote_to_response(obs: None, freshness: dict | None = ...) -> None: ...
def quote_to_response(obs: MarketObservation | None, freshness: dict | None = None) -> QuoteResponse | None:
    if obs is None:
        return None
    return QuoteResponse(
        symbol=obs.symbol,
        name=display_name(obs.symbol),
        price=obs.price,
        previous_close=obs.previous_close,
        change_pct=obs.change_pct,
        open=obs.open,
        high=obs.high,
        low=obs.low,
        volume=obs.volume,
        currency=obs.currency,
        observed_at=obs.observed_at,
        freshness=freshness or {},
    )


@overload
def change_to_response(change: ChangeEvent) -> ChangeResponse: ...
@overload
def change_to_response(change: None) -> None: ...
def change_to_response(change: ChangeEvent | None) -> ChangeResponse | None:
    if change is None:
        return None
    return ChangeResponse(
        id=change.id,
        symbol=change.symbol,
        name=display_name(change.symbol),
        detected_at=change.detected_at,
        since=change.since,
        change_type=change.change_type.value,
        severity=change.severity.value,
        attention_score=change.attention_score,
        primary_reason=change.primary_reason.value,
        status=change.status.value,
        headline=change.headline,
        data_quality=change.data_quality.value,
        is_synthetic=change.is_synthetic,
        metrics=ChangeMetricsResponse(**change.metrics.model_dump()),
        breakdown=ScoreBreakdownResponse(**change.breakdown.model_dump()),
        evidence=[
            EvidenceResponse(
                evidence_type=e.evidence_type.value,
                label=e.label,
                value=e.value,
                unit=e.unit,
                source_ref=e.source_ref,
                weight_contribution=e.weight_contribution,
                metadata=e.metadata,
            )
            for e in change.evidence
        ],
    )


def news_to_response(item: NewsEvent) -> NewsResponse:
    return NewsResponse(
        event_id=item.event_id,
        symbol=item.symbol,
        event_type=item.event_type.value,
        headline=item.headline,
        summary=item.summary,
        source=item.source,
        source_url=item.source_url,
        published_at=item.published_at,
        entity_confidence=item.entity_confidence,
        event_significance=item.event_significance,
        article_count=item.article_count,
    )


def activity_to_response(event: ActivityEvent) -> ActivityResponse:
    return ActivityResponse(
        event_type=event.event_type.value,
        symbol=event.symbol,
        metadata=event.metadata,
        created_at=event.created_at,
    )


@overload
def history_to_response(history: PriceHistory, interval: str = ...) -> HistoryResponse: ...
@overload
def history_to_response(history: None, interval: str = ...) -> None: ...
def history_to_response(history: PriceHistory | None, interval: str = "1d") -> HistoryResponse | None:
    if history is None:
        return None
    return HistoryResponse(
        symbol=history.symbol,
        interval=interval,
        source=history.source,
        is_synthetic=history.is_synthetic,
        bars=[HistoryBar(**b.model_dump()) for b in history.bars],
    )


def market_to_response(state: MarketState) -> MarketStatusResponse:
    return MarketStatusResponse(
        status=state.status.value,
        label=state.label,
        as_of=state.as_of,
        next_open=state.next_open,
        last_close=state.last_close,
    )

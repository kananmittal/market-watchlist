"""Shared test fixtures."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models.domain import MarketObservation, NewsEvent, OHLCBar, UserSymbolState, utcnow
from app.models.enums import NewsEventType


@pytest.fixture
def make_bars():
    """Deterministic OHLC history with a controllable daily volatility."""

    def _make(
        *, daily_pct: float = 1.0, base: float = 3000.0, n: int = 60, volume: float = 2_500_000.0
    ) -> list[OHLCBar]:
        bars: list[OHLCBar] = []
        price = base
        for i in range(n):
            price *= 1 + ((daily_pct if i % 2 else -daily_pct * 0.8) / 100)
            bars.append(
                OHLCBar(
                    timestamp=utcnow() - timedelta(days=n - i),
                    open=price * 0.998,
                    high=price * 1.006,
                    low=price * 0.994,
                    close=price,
                    volume=volume,
                )
            )
        return bars

    return _make


@pytest.fixture
def make_obs():
    def _make(
        symbol: str,
        price: float,
        previous: float | None = None,
        *,
        volume: float = 2_500_000.0,
        change_pct: float | None = None,
        source: str = "test",
        synthetic: bool = False,
        age_seconds: int = 0,
    ) -> MarketObservation:
        computed = change_pct
        if computed is None and previous:
            computed = round((price - previous) / previous * 100, 4)
        return MarketObservation(
            symbol=symbol,
            observed_at=utcnow() - timedelta(seconds=age_seconds),
            source=source,
            price=price,
            previous_close=previous,
            volume=volume,
            change_pct=computed,
            is_synthetic=synthetic,
        )

    return _make


@pytest.fixture
def make_news():
    def _make(
        symbol: str = "TCS",
        *,
        significance: float = 0.9,
        confidence: float = 0.95,
        event_type: NewsEventType = NewsEventType.EARNINGS,
        headline: str = "Company reports quarterly results",
        dedupe_key: str = "k1",
    ) -> NewsEvent:
        return NewsEvent(
            event_id=f"evt_{dedupe_key}",
            symbol=symbol,
            event_type=event_type,
            headline=headline,
            source="Reuters",
            published_at=utcnow(),
            entity_confidence=confidence,
            event_significance=significance,
            dedupe_key=dedupe_key,
        )

    return _make


@pytest.fixture
def make_user_state():
    def _make(symbol: str = "TCS", *, interest: float = 0.0, user_id: str = "u1") -> UserSymbolState:
        return UserSymbolState(user_id=user_id, symbol=symbol, interest_score=interest)

    return _make

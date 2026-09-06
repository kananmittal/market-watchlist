"""Pydantic request/response schemas. All API input is validated here."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator


# ---------------- auth ----------------
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=60)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str
    is_demo: bool = False
    created_at: datetime
    last_dashboard_view_at: datetime | None = None


# ---------------- watchlists ----------------
class CreateWatchlistRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)

    @field_validator("name")
    @classmethod
    def _clean(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Name cannot be blank")
        return cleaned


class RenameWatchlistRequest(CreateWatchlistRequest):
    pass


class AddItemRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=25)

    @field_validator("symbol")
    @classmethod
    def _upper(cls, v: str) -> str:
        cleaned = v.strip().upper()
        if not cleaned:
            raise ValueError("Symbol cannot be blank")
        return cleaned


class ReorderRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=50)


class WatchlistItemResponse(BaseModel):
    symbol: str
    display_name: str | None = None
    added_at: datetime
    sort_order: int = 0


class WatchlistResponse(BaseModel):
    id: str
    name: str
    items: list[WatchlistItemResponse]
    created_at: datetime
    updated_at: datetime


# ---------------- market ----------------
class SymbolSearchResult(BaseModel):
    symbol: str
    name: str
    sector: str
    is_index: bool = False


class QuoteResponse(BaseModel):
    symbol: str
    name: str
    price: float | None
    previous_close: float | None = None
    change_pct: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None
    currency: str = "INR"
    observed_at: datetime | None = None
    freshness: dict[str, Any] = Field(default_factory=dict)


class HistoryBar(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class HistoryResponse(BaseModel):
    symbol: str
    interval: str
    source: str
    is_synthetic: bool = False
    bars: list[HistoryBar]


# ---------------- changes ----------------
class EvidenceResponse(BaseModel):
    evidence_type: str
    label: str
    value: float | None = None
    unit: str | None = None
    source_ref: str | None = None
    weight_contribution: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScoreBreakdownResponse(BaseModel):
    abnormality: float = 0.0
    relative_move: float = 0.0
    volume: float = 0.0
    news: float = 0.0
    base_significance: float = 0.0
    user_adjustment: float = 0.0
    total: float = 0.0


class ChangeMetricsResponse(BaseModel):
    price_change_pct: float | None = None
    relative_to_benchmark_pct: float | None = None
    relative_to_sector_pct: float | None = None
    volume_multiple: float | None = None
    normalized_move: float | None = None
    expected_daily_move_pct: float | None = None
    news_event_count: int = 0
    max_news_significance: float = 0.0


class ChangeResponse(BaseModel):
    id: str
    symbol: str
    name: str
    detected_at: datetime
    since: datetime
    change_type: str
    severity: str
    attention_score: float
    primary_reason: str
    status: str
    headline: str
    data_quality: str
    is_synthetic: bool = False
    metrics: ChangeMetricsResponse
    breakdown: ScoreBreakdownResponse
    evidence: list[EvidenceResponse]


# ---------------- news / activity ----------------
class NewsResponse(BaseModel):
    event_id: str
    symbol: str
    event_type: str
    headline: str
    summary: str | None = None
    source: str
    source_url: str | None = None
    published_at: datetime
    entity_confidence: float
    event_significance: float
    article_count: int = 1


class ActivityResponse(BaseModel):
    event_type: str
    symbol: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


# ---------------- dashboard ----------------
class MarketStatusResponse(BaseModel):
    status: str
    label: str
    as_of: datetime
    next_open: datetime | None = None
    last_close: datetime | None = None


class WatchlistRowResponse(BaseModel):
    symbol: str
    name: str
    quote: QuoteResponse | None = None
    change: ChangeResponse | None = None
    news: list[NewsResponse] = Field(default_factory=list)
    last_viewed_at: datetime | None = None
    last_acknowledged_at: datetime | None = None


class CatchUpResponse(BaseModel):
    headline: str
    high_count: int
    medium_count: int
    meaningful_count: int
    normal_count: int
    unreviewed_count: int
    by_type: dict[str, int]
    top: list[dict[str, Any]]


class DashboardResponse(BaseModel):
    last_checked_at: datetime | None
    away_for: str
    is_first_visit: bool
    demo_mode: bool
    market: MarketStatusResponse
    benchmark: QuoteResponse | None = None
    catch_up: CatchUpResponse
    meaningful_changes: list[ChangeResponse]
    normal_movements: list[ChangeResponse]
    watchlist: list[WatchlistRowResponse]


class StockDetailResponse(BaseModel):
    symbol: str
    name: str
    sector: str | None = None
    quote: QuoteResponse | None = None
    change: ChangeResponse | None = None
    benchmark: QuoteResponse | None = None
    sector_index: QuoteResponse | None = None
    history: HistoryResponse | None = None
    news: list[NewsResponse] = Field(default_factory=list)
    activity: list[ActivityResponse] = Field(default_factory=list)
    last_viewed_at: datetime | None = None
    last_acknowledged_at: datetime | None = None


# ---------------- copilot ----------------
class CopilotRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    symbol: str | None = Field(default=None, max_length=25)


class CopilotResponse(BaseModel):
    answer: str
    grounded: bool
    evidence: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    model: str | None = None
    degraded_reason: str | None = None
    cached: bool = False


# ---------------- health ----------------
class HealthResponse(BaseModel):
    status: str
    app_env: str
    demo_mode: bool
    version: str = "0.1.0"


TokenResponse.model_rebuild()

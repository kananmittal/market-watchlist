"""Core domain models.

Strict separation is intentional:

  MarketObservation / NewsEvent  -> global truth, shared by all users
  UserSymbolState / ActivityEvent -> per-user truth
  ChangeEvent + Evidence          -> product interpretation

Never merge these. Duplicating market snapshots per user does not scale.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    ActivityType,
    ChangeStatus,
    ChangeType,
    DataQuality,
    EvidenceType,
    Freshness,
    NewsEventType,
    PrimaryReason,
    Severity,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(BaseModel):
    model_config = ConfigDict(use_enum_values=False, populate_by_name=True)


# --------------------------------------------------------------------------
# Global market truth
# --------------------------------------------------------------------------
class MarketObservation(Base):
    """A single point-in-time observation of a symbol from one provider.

    Every observation carries its provenance and age so the UI can never
    silently present stale data as live.
    """

    symbol: str
    observed_at: datetime  # when the market data itself is timestamped
    received_at: datetime = Field(default_factory=utcnow)  # when we fetched it
    source: str
    source_timestamp: datetime | None = None

    price: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    previous_close: float | None = None
    volume: float | None = None

    change_pct: float | None = None
    benchmark_symbol: str | None = None
    benchmark_return_pct: float | None = None
    sector_symbol: str | None = None
    sector_return_pct: float | None = None

    currency: str = "INR"
    quality: DataQuality = DataQuality.OK
    is_synthetic: bool = False
    notes: list[str] = Field(default_factory=list)

    def age_seconds(self, now: datetime | None = None) -> float:
        ref = now or utcnow()
        observed = self.observed_at
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        return max((ref - observed).total_seconds(), 0.0)

    def freshness(self, fresh_max: int, delayed_max: int, now: datetime | None = None) -> Freshness:
        if self.price is None:
            return Freshness.UNAVAILABLE
        age = self.age_seconds(now)
        if age <= fresh_max:
            return Freshness.LIVE
        if age <= delayed_max:
            return Freshness.DELAYED
        return Freshness.STALE


class OHLCBar(Base):
    """One historical bar."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class PriceHistory(Base):
    symbol: str
    bars: list[OHLCBar] = Field(default_factory=list)
    source: str = "unknown"
    fetched_at: datetime = Field(default_factory=utcnow)
    is_synthetic: bool = False


# --------------------------------------------------------------------------
# Global event truth
# --------------------------------------------------------------------------
class NewsEvent(Base):
    """A normalized event, deduplicated across articles covering one story."""

    event_id: str
    symbol: str
    event_type: NewsEventType = NewsEventType.GENERAL
    headline: str
    summary: str | None = None
    source: str
    source_url: str | None = None
    published_at: datetime

    entity_confidence: float = 0.5  # 0-1: how sure we are it is about this symbol
    event_significance: float = 0.3  # 0-1: how material the event class is
    dedupe_key: str = ""
    article_count: int = 1  # how many articles collapsed into this event
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def weighted_significance(self) -> float:
        """Significance discounted by how confident we are in the symbol match."""
        return round(self.event_significance * self.entity_confidence, 4)


# --------------------------------------------------------------------------
# Per-user truth
# --------------------------------------------------------------------------
class UserSymbolState(Base):
    """What THIS user has seen for THIS symbol. Never global."""

    user_id: str
    symbol: str
    first_added_at: datetime = Field(default_factory=utcnow)
    last_viewed_at: datetime | None = None
    last_acknowledged_at: datetime | None = None
    view_count: int = 0
    interest_score: float = 0.0  # 0-1, bounded


class ActivityEvent(Base):
    user_id: str
    event_type: ActivityType
    symbol: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------
# Product interpretation
# --------------------------------------------------------------------------
class Evidence(Base):
    """One concrete, checkable fact backing an attention score.

    Every attention result must be explainable through these. A bare score
    with no evidence is a product bug.
    """

    evidence_type: EvidenceType
    label: str  # human sentence, e.g. "Volume 2.8x the 20-day average"
    value: float | None = None
    unit: str | None = None
    source_ref: str | None = None
    weight_contribution: float = 0.0  # points this contributed to the score
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChangeMetrics(Base):
    price_change_pct: float | None = None
    relative_to_benchmark_pct: float | None = None
    relative_to_sector_pct: float | None = None
    volume_multiple: float | None = None
    normalized_move: float | None = None  # |return| / expected daily move
    expected_daily_move_pct: float | None = None
    news_event_count: int = 0
    max_news_significance: float = 0.0


class ScoreBreakdown(Base):
    """Transparent scoring. Each component is bounded by its own maximum."""

    abnormality: float = 0.0  # max 25
    relative_move: float = 0.0  # max 20
    volume: float = 0.0  # max 15
    news: float = 0.0  # max 25
    base_significance: float = 0.0  # sum of the four above (max 85)
    user_adjustment: float = 0.0  # max 15, additive not multiplicative
    total: float = 0.0  # clamped 0-100


class ChangeEvent(Base):
    """The central domain object the whole product consumes."""

    id: str
    user_id: str
    symbol: str
    detected_at: datetime = Field(default_factory=utcnow)
    since: datetime  # the user's own reference point

    change_type: ChangeType = ChangeType.NO_MATERIAL_CHANGE
    severity: Severity = Severity.NORMAL
    attention_score: float = 0.0
    primary_reason: PrimaryReason = PrimaryReason.NO_SIGNAL
    status: ChangeStatus = ChangeStatus.NEW

    metrics: ChangeMetrics = Field(default_factory=ChangeMetrics)
    breakdown: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    evidence: list[Evidence] = Field(default_factory=list)

    headline: str = ""
    data_quality: DataQuality = DataQuality.OK
    is_synthetic: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @property
    def is_material(self) -> bool:
        return self.change_type is not ChangeType.NO_MATERIAL_CHANGE

    @property
    def evidence_labels(self) -> list[str]:
        return [e.label for e in self.evidence]


# --------------------------------------------------------------------------
# Account / watchlist
# --------------------------------------------------------------------------
class User(Base):
    id: str
    email: str
    display_name: str
    password_hash: str | None = None
    is_demo: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    last_active_at: datetime | None = None
    # The dashboard's "when did I last look?" anchor.
    last_dashboard_view_at: datetime | None = None


class WatchlistItem(Base):
    symbol: str
    display_name: str | None = None
    added_at: datetime = Field(default_factory=utcnow)
    sort_order: int = 0


class Watchlist(Base):
    id: str
    user_id: str
    name: str
    items: list[WatchlistItem] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

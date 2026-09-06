"""Shared domain vocabulary.

These enums are the contract between the change engine, the API and the UI.
Keeping them in one place stops "severity" meaning three different things.
"""

from __future__ import annotations

from enum import StrEnum


class ChangeType(StrEnum):
    """Why a move happened - the attribution."""

    COMPANY_SPECIFIC = "COMPANY_SPECIFIC"
    SECTOR_DRIVEN = "SECTOR_DRIVEN"
    MARKET_DRIVEN = "MARKET_DRIVEN"
    TECHNICAL = "TECHNICAL"
    NO_MATERIAL_CHANGE = "NO_MATERIAL_CHANGE"


class Severity(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    NORMAL = "NORMAL"


class ChangeStatus(StrEnum):
    """Attention lifecycle. An event must not stay red forever."""

    NEW = "NEW"
    IMPORTANT = "IMPORTANT"
    VIEWED = "VIEWED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISMISSED = "DISMISSED"
    STALE = "STALE"


class PrimaryReason(StrEnum):
    COMPANY_EVENT = "COMPANY_EVENT"
    ABNORMAL_MOVE = "ABNORMAL_MOVE"
    VOLUME_SPIKE = "VOLUME_SPIKE"
    BENCHMARK_DIVERGENCE = "BENCHMARK_DIVERGENCE"
    SECTOR_MOVE = "SECTOR_MOVE"
    MARKET_MOVE = "MARKET_MOVE"
    NO_SIGNAL = "NO_SIGNAL"


class DataQuality(StrEnum):
    """How much the system trusts an observation."""

    OK = "OK"
    DELAYED = "DELAYED"
    STALE = "STALE"
    CONFLICTED = "CONFLICTED"
    UNAVAILABLE = "UNAVAILABLE"
    SYNTHETIC = "SYNTHETIC"  # demo data - never present as real


class Freshness(StrEnum):
    LIVE = "LIVE"
    DELAYED = "DELAYED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class EvidenceType(StrEnum):
    PRICE_MOVE = "PRICE_MOVE"
    ABNORMALITY = "ABNORMALITY"
    BENCHMARK = "BENCHMARK"
    SECTOR = "SECTOR"
    VOLUME = "VOLUME"
    NEWS = "NEWS"
    USER_CONTEXT = "USER_CONTEXT"
    DATA_QUALITY = "DATA_QUALITY"


class NewsEventType(StrEnum):
    EARNINGS = "EARNINGS"
    MERGER_ACQUISITION = "MERGER_ACQUISITION"
    REGULATORY = "REGULATORY"
    LEGAL = "LEGAL"
    MANAGEMENT = "MANAGEMENT"
    CORPORATE_ACTION = "CORPORATE_ACTION"
    PRODUCT_BUSINESS = "PRODUCT_BUSINESS"
    ANALYST = "ANALYST"
    SECTOR = "SECTOR"
    GENERAL = "GENERAL"


class ActivityType(StrEnum):
    WATCHLIST_CREATED = "WATCHLIST_CREATED"
    WATCHLIST_RENAMED = "WATCHLIST_RENAMED"
    WATCHLIST_DELETED = "WATCHLIST_DELETED"
    STOCK_ADDED = "STOCK_ADDED"
    STOCK_REMOVED = "STOCK_REMOVED"
    STOCK_VIEWED = "STOCK_VIEWED"
    STOCK_SEARCHED = "STOCK_SEARCHED"
    CHART_VIEWED = "CHART_VIEWED"
    NEWS_VIEWED = "NEWS_VIEWED"
    CHANGE_VIEWED = "CHANGE_VIEWED"
    CHANGE_ACKNOWLEDGED = "CHANGE_ACKNOWLEDGED"
    CHANGE_DISMISSED = "CHANGE_DISMISSED"
    COPILOT_QUERY = "COPILOT_QUERY"
    DASHBOARD_VIEWED = "DASHBOARD_VIEWED"


class ProviderName(StrEnum):
    YFINANCE = "yfinance"
    JUGAAD = "jugaad"
    UPSTOX = "upstox"
    DEMO = "demo"

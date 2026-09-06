"""Dashboard assembly - the "since you last looked" experience.

Answers, in order:
  1. When did I last look?
  2. What changed?
  3. Which changes matter?
  4. Why do they matter?
  5. Have I already reviewed them?

Everything is assembled from batched reads. A watchlist of N symbols costs a
constant number of upstream calls and database queries, not N.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.core.logging import get_logger
from app.core.market_time import MarketState, describe_gap, get_market_state
from app.models.domain import ChangeEvent, MarketObservation, NewsEvent, utcnow
from app.models.enums import ActivityType, ChangeStatus, Severity
from app.providers.symbols import BENCHMARK_SYMBOL, display_name, sector_index_for
from app.repositories.changes import ChangeEventRepository
from app.repositories.news import NewsRepository
from app.repositories.users import UserRepository
from app.repositories.watchlists import WatchlistRepository
from app.services.change_engine import ChangeEngine, ChangeInput
from app.services.market_data import MarketDataService
from app.services.news_engine import NewsEngine
from app.services.user_memory import UserMemoryService

log = get_logger("service.dashboard")

#: How long a first-time user's "since" window looks back.
DEFAULT_LOOKBACK_HOURS = 24
#: Changes older than this are archived rather than shown as current.
STALE_AFTER_DAYS = 7


@dataclass
class SymbolView:
    """One row of the watchlist, fully resolved."""

    symbol: str
    name: str
    observation: MarketObservation | None
    change: ChangeEvent | None
    freshness: dict[str, object]
    news: list[NewsEvent] = field(default_factory=list)
    last_viewed_at: datetime | None = None
    last_acknowledged_at: datetime | None = None


@dataclass
class DashboardResult:
    last_checked_at: datetime | None
    away_for: str
    market: MarketState
    benchmark: MarketObservation | None
    symbols: list[SymbolView]
    meaningful_changes: list[ChangeEvent]
    normal_movements: list[ChangeEvent]
    unreviewed_count: int
    is_first_visit: bool
    demo_mode: bool


class DashboardService:
    def __init__(self, market: MarketDataService | None = None) -> None:
        self.market = market or MarketDataService()
        self.news_engine = NewsEngine()
        self.change_engine = ChangeEngine()
        self.memory = UserMemoryService()
        self.watchlists = WatchlistRepository()
        self.users = UserRepository()
        self.changes = ChangeEventRepository()
        self.news_repo = NewsRepository()

    # ------------------------------------------------------------------
    async def build(
        self, user_id: str, *, advance_anchor: bool = True, include_news: bool = True
    ) -> DashboardResult:
        market_state = get_market_state()

        # 1. The user's own reference point. Read-and-stamp is atomic, and we
        #    read the PREVIOUS value - that is "when did I last look".
        if advance_anchor:
            last_checked = await self.users.get_and_set_dashboard_view(user_id)
        else:
            user = await self.users.get_by_id(user_id)
            last_checked = user.last_dashboard_view_at if user else None
        is_first_visit = last_checked is None
        fallback = last_checked or (utcnow() - timedelta(hours=DEFAULT_LOOKBACK_HOURS))

        symbols = await self.watchlists.all_symbols_for_user(user_id)
        if not symbols:
            return DashboardResult(
                last_checked_at=last_checked,
                away_for=describe_gap(fallback) if last_checked else "first visit",
                market=market_state,
                benchmark=None,
                symbols=[],
                meaningful_changes=[],
                normal_movements=[],
                unreviewed_count=0,
                is_first_visit=is_first_visit,
                demo_mode=self.market.demo_mode,
            )

        # 2. Fetch everything concurrently and in batches.
        anchors = await self.memory.reference_points(user_id, symbols, fallback)
        quotes_task = self.market.get_quotes(symbols)
        context_task = self.market.get_context_quotes(symbols)
        states_task = self.memory.states_for(user_id, symbols)
        news_task = (
            self._load_news(symbols, since=min(anchors.values(), default=fallback))
            if include_news
            else self._no_news(symbols)
        )
        baselines_task = self._baselines(symbols, anchors)

        quotes, context, states, news_map, baselines = await asyncio.gather(
            quotes_task, context_task, states_task, news_task, baselines_task
        )

        # 3. Interest scores feed ranking only.
        try:
            interests = await self.memory.recompute_interest(user_id, symbols)
        except Exception as exc:
            log.warning("interest_recompute_failed", error=str(exc)[:160])
            interests = {}

        benchmark = context.get(BENCHMARK_SYMBOL)
        histories = await self._histories(symbols)

        # 4. Evaluate every symbol through the change engine.
        views: list[SymbolView] = []
        events: list[ChangeEvent] = []
        for symbol in symbols:
            observation = quotes.get(symbol)
            state = states.get(symbol)
            if state and symbol in interests:
                state = state.model_copy(update={"interest_score": interests[symbol]})

            sector_pair = sector_index_for(symbol)
            sector_obs = context.get(sector_pair[1]) if sector_pair else None
            history = histories.get(symbol)

            event = self.change_engine.evaluate(
                ChangeInput(
                    symbol=symbol,
                    user_id=user_id,
                    since=anchors.get(symbol, fallback),
                    current=observation,
                    baseline=baselines.get(symbol),
                    benchmark=benchmark,
                    sector=sector_obs,
                    sector_name=sector_pair[0] if sector_pair else None,
                    history=history.bars if history else [],
                    news=news_map.get(symbol, []),
                    user_state=state,
                )
            )
            events.append(event)
            views.append(
                SymbolView(
                    symbol=symbol,
                    name=display_name(symbol),
                    observation=observation,
                    change=event,
                    freshness=self.market.describe_freshness(observation),
                    news=news_map.get(symbol, [])[:3],
                    last_viewed_at=state.last_viewed_at if state else None,
                    last_acknowledged_at=state.last_acknowledged_at if state else None,
                )
            )

        # 5. Persist, then re-read so previously acknowledged statuses win.
        await self.changes.upsert_many(events)
        events = await self._merge_persisted_status(user_id, events)
        for view in views:
            for ev in events:
                if ev.symbol == view.symbol:
                    view.change = ev
                    break

        meaningful = [e for e in events if e.is_material]
        meaningful.sort(key=lambda e: (e.attention_score, e.detected_at), reverse=True)
        normal = [e for e in events if not e.is_material]

        views.sort(key=lambda v: v.change.attention_score if v.change else 0.0, reverse=True)

        await self.memory.log(user_id, ActivityType.DASHBOARD_VIEWED, metadata={"symbols": len(symbols)})

        return DashboardResult(
            last_checked_at=last_checked,
            away_for=describe_gap(last_checked) if last_checked else "first visit",
            market=market_state,
            benchmark=benchmark,
            symbols=views,
            meaningful_changes=meaningful,
            normal_movements=normal,
            unreviewed_count=await self.changes.unreviewed_count(user_id),
            is_first_visit=is_first_visit,
            demo_mode=self.market.demo_mode,
        )

    # ------------------------------------------------------------------
    async def _merge_persisted_status(self, user_id: str, events: list[ChangeEvent]) -> list[ChangeEvent]:
        """Recomputing must never resurrect a change the user already reviewed."""
        stored = {e.id: e for e in await self.changes.list_for_user(user_id, limit=300)}
        merged: list[ChangeEvent] = []
        cutoff = utcnow() - timedelta(days=STALE_AFTER_DAYS)
        for ev in events:
            prior = stored.get(ev.id)
            if prior is not None:
                ev = ev.model_copy(update={"status": prior.status})
            if ev.detected_at < cutoff and ev.status in {ChangeStatus.NEW, ChangeStatus.IMPORTANT}:
                ev = ev.model_copy(update={"status": ChangeStatus.STALE})
            merged.append(ev)
        return merged

    async def _baselines(
        self, symbols: list[str], anchors: dict[str, datetime]
    ) -> dict[str, MarketObservation]:
        """What each symbol was worth when the user last looked.

        Grouped by distinct anchor so a shared anchor costs one query, not N.
        """
        by_anchor: dict[datetime, list[str]] = {}
        for symbol in symbols:
            by_anchor.setdefault(anchors.get(symbol, utcnow()), []).append(symbol)
        results = await asyncio.gather(
            *[
                self.market.observations.observations_at_or_before_many(group, anchor)
                for anchor, group in by_anchor.items()
            ],
            return_exceptions=True,
        )
        out: dict[str, MarketObservation] = {}
        for res in results:
            if isinstance(res, dict):
                out.update(res)
        return out

    async def _histories(self, symbols: list[str]) -> dict[str, object]:
        """Historical bars power the volatility and volume baselines."""
        results = await asyncio.gather(*(self.market.get_history(s) for s in symbols), return_exceptions=True)
        return {
            sym: res
            for sym, res in zip(symbols, results, strict=False)
            if res is not None and not isinstance(res, BaseException)
        }

    async def _no_news(self, symbols: list[str]) -> dict[str, list[NewsEvent]]:
        return {s: [] for s in symbols}

    async def _load_news(self, symbols: list[str], *, since: datetime) -> dict[str, list[NewsEvent]]:
        """Serve cached news when fresh; otherwise refresh and persist.

        Correctness does not depend on a background worker, because free hosting
        tiers sleep.
        """
        try:
            cached = await self.news_repo.for_symbols(symbols, since=since - timedelta(days=3))
            stale = [s for s in symbols if not await self.news_repo.has_recent(s, minutes=15)]
            if stale:
                fetched = await self.news_engine.fetch_and_normalize_many(stale)
                flat = [e for events in fetched.values() for e in events]
                if flat:
                    await self.news_repo.upsert_many(flat)
                for sym, events in fetched.items():
                    cached[sym] = events
            return cached
        except Exception as exc:
            log.warning("news_load_failed", error=str(exc)[:160])
            return {s: [] for s in symbols}

    # ------------------------------------------------------------------
    def catch_me_up(self, result: DashboardResult) -> dict[str, object]:
        """The deterministic Catch Me Up summary. No LLM required."""
        high = [e for e in result.meaningful_changes if e.severity is Severity.HIGH]
        medium = [e for e in result.meaningful_changes if e.severity is Severity.MEDIUM]
        by_type: dict[str, int] = {}
        for ev in result.meaningful_changes:
            by_type[ev.change_type.value] = by_type.get(ev.change_type.value, 0) + 1

        if result.is_first_visit:
            headline = "Welcome - here is where your watchlist stands right now."
        elif not result.meaningful_changes:
            headline = f"You were away {result.away_for}. Nothing material changed."
        else:
            n = len(result.meaningful_changes)
            headline = (
                f"You were away {result.away_for}. "
                f"{n} meaningful change{'s' if n != 1 else ''} "
                f"and {len(result.normal_movements)} normal movement"
                f"{'s' if len(result.normal_movements) != 1 else ''}."
            )
        return {
            "headline": headline,
            "high_count": len(high),
            "medium_count": len(medium),
            "meaningful_count": len(result.meaningful_changes),
            "normal_count": len(result.normal_movements),
            "unreviewed_count": result.unreviewed_count,
            "by_type": by_type,
            "top": [
                {
                    "symbol": e.symbol,
                    "name": display_name(e.symbol),
                    "headline": e.headline,
                    "severity": e.severity.value,
                    "attention_score": e.attention_score,
                    "change_type": e.change_type.value,
                    "evidence": e.evidence_labels[:4],
                    "status": e.status.value,
                }
                for e in result.meaningful_changes[:5]
            ],
        }

"""Market data orchestration.

Responsibilities:
  * choose providers in configured priority order and fall through on failure
  * serve many users from ONE upstream fetch per symbol (shared observations)
  * cache in memory (hot) and in MongoDB (durable, survives Render cold starts)
  * detect and surface disagreement between providers instead of averaging it
  * label freshness honestly - stale data is never dressed up as live

Correctness never depends on a background worker running, because free
hosting tiers sleep. Reads refresh on demand when the cache is cold.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from datetime import datetime

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.market_time import get_market_state
from app.models.domain import MarketObservation, PriceHistory
from app.models.enums import DataQuality, Freshness
from app.providers.base import MarketDataProvider
from app.providers.demo_provider import DemoProvider
from app.providers.jugaad_provider import JugaadProvider
from app.providers.symbols import BENCHMARK_SYMBOL, sector_index_for
from app.providers.yfinance_provider import YFinanceProvider
from app.repositories.market import MarketObservationRepository, PriceHistoryRepository

log = get_logger("service.market")


@dataclass
class _CacheEntry:
    value: object
    expires_at: float


@dataclass
class _TTLCache:
    """Tiny process-local TTL cache. Redis is not required for a hackathon,
    and one process on Render free tier makes a shared cache pointless."""

    data: dict[str, _CacheEntry] = field(default_factory=dict)

    def get(self, key: str) -> object | None:
        entry = self.data.get(key)
        if entry is None:
            return None
        if entry.expires_at < time.monotonic():
            self.data.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: object, ttl: int) -> None:
        self.data[key] = _CacheEntry(value, time.monotonic() + ttl)

    def clear(self) -> None:
        self.data.clear()


@dataclass
class ConflictReport:
    symbol: str
    prices: dict[str, float]
    spread_pct: float
    tolerance_pct: float

    @property
    def is_conflict(self) -> bool:
        return self.spread_pct > self.tolerance_pct


class MarketDataService:
    def __init__(self, *, demo_step: int = 1) -> None:
        self.settings = get_settings()
        self.cache = _TTLCache()
        self.observations = MarketObservationRepository()
        self.history_repo = PriceHistoryRepository()
        self._demo_step = demo_step
        self._providers: dict[str, MarketDataProvider] = {}
        self._build_providers()

    # ---------------- provider wiring ----------------
    def _build_providers(self) -> None:
        available: dict[str, MarketDataProvider] = {
            "yfinance": YFinanceProvider(),
            "jugaad": JugaadProvider(),
            "demo": DemoProvider(step=self._demo_step),
        }
        for name in self.settings.provider_order:
            if name in available:
                self._providers[name] = available[name]
        if not self._providers:  # never leave the product with no source
            self._providers["demo"] = available["demo"]

    @property
    def demo_mode(self) -> bool:
        return self.settings.demo_mode

    def set_demo_step(self, step: int) -> None:
        self._demo_step = step
        provider = self._providers.get("demo")
        if isinstance(provider, DemoProvider):
            provider.step = step

    def _ordered_providers(self) -> list[MarketDataProvider]:
        """Demo mode short-circuits to the deterministic provider so a demo
        never depends on the network."""
        if self.demo_mode:
            return [self._providers.get("demo") or DemoProvider(step=self._demo_step)]
        # Live mode: demo is a last-resort fallback for symbols nobody could
        # answer, NOT a peer source. Including it would make synthetic prices
        # disagree with real ones and raise phantom DATA_CONFLICTs.
        return [p for p in self._providers.values() if not p.synthetic]

    # ---------------- conflict detection ----------------
    def detect_conflict(self, symbol: str, obs: list[MarketObservation]) -> ConflictReport:
        prices = {o.source: o.price for o in obs if o.price is not None}
        if len(prices) < 2:
            return ConflictReport(symbol, prices, 0.0, self.settings.price_conflict_tolerance_pct)
        lo, hi = min(prices.values()), max(prices.values())
        spread = ((hi - lo) / lo * 100) if lo else 0.0
        return ConflictReport(symbol, prices, round(spread, 4), self.settings.price_conflict_tolerance_pct)

    def _resolve(self, symbol: str, candidates: list[MarketObservation]) -> MarketObservation | None:
        """Pick a winner without averaging.

        Preference order: real data over synthetic, then provider priority,
        then freshness. When providers disagree beyond tolerance the winner is
        still returned but marked CONFLICTED so the UI can say so.
        """
        usable = [o for o in candidates if o.price is not None]
        if not usable:
            return None

        conflict = self.detect_conflict(symbol, usable)
        priority = {p.name: p.priority for p in self._providers.values()}
        usable.sort(
            key=lambda o: (not o.is_synthetic, priority.get(o.source, 0), o.observed_at),
            reverse=True,
        )
        winner = usable[0].model_copy(deep=True)

        if conflict.is_conflict:
            winner.quality = DataQuality.CONFLICTED
            others = ", ".join(f"{s}={p:.2f}" for s, p in sorted(conflict.prices.items()))
            winner.notes.append(
                f"Sources disagree by {conflict.spread_pct:.2f}% "
                f"(tolerance {conflict.tolerance_pct:.2f}%): {others}. Value under verification."
            )
            log.warning(
                "data_conflict",
                symbol=symbol,
                spread_pct=conflict.spread_pct,
                sources=list(conflict.prices),
            )
        return winner

    # ---------------- quotes ----------------
    async def get_quotes(
        self, symbols: list[str], *, force_refresh: bool = False
    ) -> dict[str, MarketObservation]:
        """Batched, cached, shared-across-users quote fetch."""
        wanted = [s.strip().upper() for s in symbols if s and s.strip()]
        if not wanted:
            return {}

        results: dict[str, MarketObservation] = {}
        missing: list[str] = []
        if not force_refresh:
            for sym in wanted:
                cached = self.cache.get(f"q:{sym}")
                if isinstance(cached, MarketObservation):
                    results[sym] = cached
                else:
                    missing.append(sym)
        else:
            missing = list(wanted)

        if not missing:
            return results

        # Ask every configured provider once, in parallel, for all missing symbols.
        providers = self._ordered_providers()
        gathered = await asyncio.gather(
            *(p.get_batch_quotes(missing) for p in providers), return_exceptions=True
        )

        per_symbol: dict[str, list[MarketObservation]] = {s: [] for s in missing}
        for provider, outcome in zip(providers, gathered, strict=False):
            if isinstance(outcome, BaseException):
                log.warning("provider_batch_failed", provider=provider.name, error=str(outcome)[:160])
                continue
            for sym, obs in outcome.items():
                if sym in per_symbol:
                    per_symbol[sym].append(obs)

        # Anything no real provider answered falls back to demo data, clearly labelled.
        unanswered = [s for s, obs in per_symbol.items() if not obs]
        if unanswered and not self.demo_mode:
            fallback = self._providers.get("demo") or DemoProvider(step=self._demo_step)
            try:
                for sym, obs in (await fallback.get_batch_quotes(unanswered)).items():
                    obs.notes.append("All live providers unavailable - showing demo data")
                    per_symbol[sym].append(obs)
            except Exception as exc:
                log.warning("demo_fallback_failed", error=str(exc)[:160])

        to_persist: list[MarketObservation] = []
        for sym, candidates in per_symbol.items():
            # market_observations holds shared global market TRUTH. Synthetic
            # rows would outrank real ones on recency and corrupt every user's
            # baseline, so store them only when demo mode owns the system.
            to_persist.extend(c for c in candidates if self.demo_mode or not c.is_synthetic)
            winner = self._resolve(sym, candidates)
            if winner is not None:
                results[sym] = winner
                self.cache.set(f"q:{sym}", winner, self.settings.quote_cache_ttl_seconds)

        if to_persist:
            try:
                await self.observations.save_many(to_persist)
            except Exception as exc:  # persistence must never break a read
                log.warning("observation_persist_failed", error=str(exc)[:160])

        return results

    async def get_quote(self, symbol: str, *, force_refresh: bool = False) -> MarketObservation | None:
        return (await self.get_quotes([symbol], force_refresh=force_refresh)).get(symbol.strip().upper())

    # ---------------- benchmark & sector ----------------
    async def get_context_quotes(self, symbols: list[str]) -> dict[str, MarketObservation]:
        """Benchmark plus every relevant sector index, fetched once for a whole
        watchlist rather than once per symbol."""
        needed = {BENCHMARK_SYMBOL}
        sector_tickers: dict[str, str] = {}
        for sym in symbols:
            pair = sector_index_for(sym)
            if pair:
                name, ticker = pair
                sector_tickers[ticker] = name
        needed.update(sector_tickers.keys())
        return await self.get_quotes(sorted(needed))

    # ---------------- history ----------------
    async def get_history(
        self, symbol: str, *, period: str = "3mo", interval: str = "1d", force_refresh: bool = False
    ) -> PriceHistory | None:
        symbol = symbol.strip().upper()
        key = f"h:{symbol}:{period}:{interval}"
        if not force_refresh:
            cached = self.cache.get(key)
            if isinstance(cached, PriceHistory):
                return cached
            stored = await self.history_repo.get(
                symbol, interval, max_age_seconds=self.settings.history_cache_ttl_seconds
            )
            if stored and stored.bars:
                self.cache.set(key, stored, self.settings.history_cache_ttl_seconds)
                return stored

        for provider in self._ordered_providers():
            try:
                history = await provider.get_history(symbol, period=period, interval=interval)
            except Exception as exc:
                log.warning("history_failed", provider=provider.name, symbol=symbol, error=str(exc)[:160])
                continue
            if history and history.bars:
                self.cache.set(key, history, self.settings.history_cache_ttl_seconds)
                with contextlib.suppress(Exception):
                    await self.history_repo.save(history, interval)
                return history
        return None

    # ---------------- freshness ----------------
    def freshness_of(self, obs: MarketObservation, now: datetime | None = None) -> Freshness:
        return obs.freshness(self.settings.fresh_max_age_seconds, self.settings.delayed_max_age_seconds, now)

    def describe_freshness(self, obs: MarketObservation | None) -> dict[str, object]:
        """Everything the UI needs to label data honestly."""
        if obs is None or obs.price is None:
            return {
                "freshness": Freshness.UNAVAILABLE.value,
                "label": "Unavailable",
                "age_seconds": None,
                "source": None,
                "is_synthetic": False,
                "quality": DataQuality.UNAVAILABLE.value,
            }
        fresh = self.freshness_of(obs)
        age = int(obs.age_seconds())
        market = get_market_state()
        if obs.is_synthetic:
            label = "Demo data"
        elif fresh is Freshness.LIVE:
            label = "Updated just now"
        elif fresh is Freshness.DELAYED:
            label = f"Delayed - updated {max(age // 60, 1)} min ago"
        elif not market.is_open and market.last_close is not None:
            # Outside trading hours, last-session data is expected, not a fault.
            # Labelling it "stale" would be both alarming and wrong.
            label = f"At {market.last_close:%a %d %b} close"
        else:
            hours = age // 3600
            label = f"Last known - {hours}h ago" if hours else f"Last known - {max(age // 60, 1)} min ago"
        return {
            "freshness": fresh.value,
            "label": label,
            "age_seconds": age,
            "source": obs.source,
            "is_synthetic": obs.is_synthetic,
            "quality": obs.quality.value,
            "observed_at": obs.observed_at,
            "notes": obs.notes,
            "market_status": market.status.value,
        }

    # ---------------- health ----------------
    async def health(self) -> list[dict[str, object]]:
        results = await asyncio.gather(
            *(p.health() for p in self._providers.values()), return_exceptions=True
        )
        out: list[dict[str, object]] = []
        for provider, res in zip(self._providers.values(), results, strict=False):
            out.append(
                res
                if isinstance(res, dict)
                else {"provider": provider.name, "ok": False, "error": "probe_failed"}
            )
        return out

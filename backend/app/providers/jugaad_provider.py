"""NSE provider via jugaad-data.

NSE's public endpoints are rate-limited and frequently return partial
payloads to non-browser clients. In testing, `stock_quote` reliably returned
security metadata (year high/low, NSE's own daily volatility, price bands)
but often omitted live price fields.

This provider is therefore treated as best-effort ENRICHMENT, never as a
required source: every method returns None rather than raising, and the
registry always has yfinance and demo behind it.

Its genuinely valuable contribution is `get_nse_metrics`: NSE's published
`cmDailyVolatility` is an exchange-computed expected daily move, which is a
better volatility baseline than one inferred from Yahoo bars.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.domain import MarketObservation, PriceHistory, utcnow
from app.models.enums import DataQuality, ProviderName
from app.providers.base import MarketDataProvider

log = get_logger("provider.jugaad")


def _f(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


class JugaadProvider(MarketDataProvider):
    name = ProviderName.JUGAAD.value
    #: Above yfinance: exchange-direct data is preferred when it actually arrives.
    priority = 70
    synthetic = False

    def __init__(self) -> None:
        self._settings = get_settings()
        self._live = None

    def _client(self):
        if self._live is None:
            from jugaad_data.nse import NSELive

            self._live = NSELive()
        return self._live

    # ---------------- quotes ----------------
    def _blocking_quote(self, symbol: str) -> MarketObservation | None:
        payload = self._client().stock_quote(symbol.strip().upper())
        if not isinstance(payload, dict):
            return None
        price_info = payload.get("priceInfo") or {}
        last = _f(price_info.get("lastPrice"))
        if last is None or last <= 0:
            # Partial payload - no usable price. Report nothing rather than guess.
            return None

        prev_close = _f(price_info.get("previousClose"))
        change_pct = _f(price_info.get("pChange"))
        intraday = price_info.get("intraDayHighLow") or {}
        trade_info = payload.get("tradeInfo") or {}
        stamp = payload.get("lastUpdateTime")
        observed = utcnow()
        if isinstance(stamp, str):
            with contextlib.suppress(ValueError):
                observed = datetime.strptime(stamp, "%d-%b-%Y %H:%M:%S").replace(tzinfo=UTC)

        return MarketObservation(
            symbol=symbol.strip().upper(),
            observed_at=observed,
            received_at=utcnow(),
            source=self.name,
            source_timestamp=observed,
            price=last,
            open=_f(price_info.get("open")),
            high=_f(intraday.get("max")),
            low=_f(intraday.get("min")),
            close=last,
            previous_close=prev_close,
            volume=_f(trade_info.get("totalTradedVolume")),
            change_pct=change_pct,
            quality=DataQuality.OK,
        )

    async def get_quote(self, symbol: str) -> MarketObservation | None:
        try:
            return await self._with_timeout(
                asyncio.to_thread(self._blocking_quote, symbol),
                self._settings.provider_timeout_seconds,
                f"quote {symbol}",
            )
        except Exception as exc:
            log.debug("jugaad_quote_unavailable", symbol=symbol, error=str(exc)[:120])
            return None

    async def get_batch_quotes(self, symbols: list[str]) -> dict[str, MarketObservation]:
        """NSE offers no batch endpoint here, so requests are issued with
        bounded concurrency. Capped deliberately: this is an enrichment source
        and must never become the slowest part of a dashboard load."""
        if not symbols:
            return {}
        capped = symbols[:12]
        sem = asyncio.Semaphore(4)

        async def one(sym: str) -> tuple[str, MarketObservation | None]:
            async with sem:
                return sym.strip().upper(), await self.get_quote(sym)

        results = await asyncio.gather(*(one(s) for s in capped), return_exceptions=True)
        out: dict[str, MarketObservation] = {}
        for res in results:
            if isinstance(res, tuple) and res[1] is not None:
                out[res[0]] = res[1]
        return out

    # ---------------- history ----------------
    async def get_history(
        self, symbol: str, period: str = "3mo", interval: str = "1d"
    ) -> PriceHistory | None:
        """Not implemented: NSE's bulk history endpoint is heavily throttled and
        yfinance already covers this reliably. Returning None lets the registry
        fall through cleanly."""
        return None

    # ---------------- enrichment ----------------
    def _blocking_metrics(self, symbol: str) -> dict[str, float] | None:
        payload = self._client().stock_quote(symbol.strip().upper())
        if not isinstance(payload, dict):
            return None
        info = payload.get("priceInfo") or {}
        metrics: dict[str, float] = {}
        for src, dst in (
            ("cmDailyVolatility", "daily_volatility_pct"),
            ("cmAnnualVolatility", "annual_volatility_pct"),
            ("yearHigh", "year_high"),
            ("yearLow", "year_low"),
        ):
            val = _f(info.get(src))
            if val is not None:
                metrics[dst] = val
        return metrics or None

    async def get_nse_metrics(self, symbol: str) -> dict[str, float] | None:
        """Exchange-published volatility and 52-week range, when reachable."""
        try:
            return await self._with_timeout(
                asyncio.to_thread(self._blocking_metrics, symbol),
                self._settings.provider_timeout_seconds,
                f"metrics {symbol}",
            )
        except Exception as exc:
            log.debug("jugaad_metrics_unavailable", symbol=symbol, error=str(exc)[:120])
            return None

    async def health(self) -> dict[str, object]:
        try:
            metrics = await self.get_nse_metrics("TCS")
            return {
                "provider": self.name,
                "ok": metrics is not None,
                "synthetic": False,
                "mode": "enrichment",
                "note": "best-effort; NSE frequently returns partial payloads",
            }
        except Exception:
            return {"provider": self.name, "ok": False, "synthetic": False, "mode": "enrichment"}

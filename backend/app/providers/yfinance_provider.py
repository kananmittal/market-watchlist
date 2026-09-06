"""Yahoo Finance provider - the primary free source for NSE data.

yfinance is synchronous and does blocking network I/O, so every call is
pushed to a worker thread and bounded by a timeout. Batch quotes use a
single multi-ticker download rather than one request per symbol.
"""

from __future__ import annotations

import asyncio
import math
import warnings
from datetime import datetime

import pandas as pd

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.domain import MarketObservation, OHLCBar, PriceHistory, utcnow
from app.models.enums import DataQuality, ProviderName
from app.providers.base import MarketDataProvider
from app.providers.symbols import to_yahoo

warnings.filterwarnings("ignore", module="yfinance")
log = get_logger("provider.yfinance")


def _f(value: object) -> float | None:
    """Coerce numpy/pandas scalars to a clean float, rejecting NaN."""
    if value is None:
        return None
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if math.isnan(out) or math.isinf(out) else out


def _to_utc(ts: object) -> datetime:
    try:
        stamp = pd.Timestamp(ts)  # type: ignore[arg-type]
        stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
        return stamp.to_pydatetime()
    except Exception:
        return utcnow()


class YFinanceProvider(MarketDataProvider):
    name = ProviderName.YFINANCE.value
    priority = 50
    synthetic = False

    def __init__(self) -> None:
        self._settings = get_settings()

    # ---------------- quotes ----------------
    def _blocking_batch(self, symbols: list[str]) -> dict[str, MarketObservation]:
        import yfinance as yf

        yahoo_map = {to_yahoo(s): s for s in symbols}
        tickers = list(yahoo_map.keys())

        # One request for every symbol. 2 days of daily bars gives us both the
        # latest close and the previous close needed for a change percentage.
        data = yf.download(
            tickers=" ".join(tickers),
            period="5d",
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=True,
        )
        if data is None or data.empty:
            return {}

        out: dict[str, MarketObservation] = {}
        for yahoo, canonical in yahoo_map.items():
            try:
                # yfinance returns MultiIndex columns (ticker, field) even for a
                # single ticker, so always select by ticker when present.
                frame = data[yahoo] if isinstance(data.columns, pd.MultiIndex) else data
                frame = frame.dropna(how="all")
                if frame.empty:
                    continue
                last = frame.iloc[-1]
                prev_close = _f(frame["Close"].iloc[-2]) if len(frame) > 1 else None
                close = _f(last.get("Close"))
                if close is None:
                    continue
                change_pct = (
                    round((close - prev_close) / prev_close * 100, 4) if prev_close not in (None, 0) else None
                )
                out[canonical] = MarketObservation(
                    symbol=canonical,
                    observed_at=_to_utc(frame.index[-1]),
                    received_at=utcnow(),
                    source=self.name,
                    source_timestamp=_to_utc(frame.index[-1]),
                    price=close,
                    open=_f(last.get("Open")),
                    high=_f(last.get("High")),
                    low=_f(last.get("Low")),
                    close=close,
                    previous_close=prev_close,
                    volume=_f(last.get("Volume")),
                    change_pct=change_pct,
                    quality=DataQuality.OK,
                )
            except (KeyError, IndexError, TypeError):
                continue
        return out

    async def get_batch_quotes(self, symbols: list[str]) -> dict[str, MarketObservation]:
        if not symbols:
            return {}
        try:
            return await self._with_timeout(
                asyncio.to_thread(self._blocking_batch, symbols),
                self._settings.provider_timeout_seconds * 2,
                f"{len(symbols)} quotes",
            )
        except Exception as exc:
            log.warning("yfinance_batch_failed", count=len(symbols), error=str(exc)[:160])
            return {}

    async def get_quote(self, symbol: str) -> MarketObservation | None:
        return (await self.get_batch_quotes([symbol])).get(symbol.strip().upper())

    # ---------------- history ----------------
    def _blocking_history(self, symbol: str, period: str, interval: str) -> PriceHistory | None:
        import yfinance as yf

        frame = yf.Ticker(to_yahoo(symbol)).history(period=period, interval=interval, auto_adjust=False)
        if frame is None or frame.empty:
            return None
        bars: list[OHLCBar] = []
        for idx, row in frame.iterrows():
            close = _f(row.get("Close"))
            if close is None:
                continue
            bars.append(
                OHLCBar(
                    timestamp=_to_utc(idx),
                    open=_f(row.get("Open")) or close,
                    high=_f(row.get("High")) or close,
                    low=_f(row.get("Low")) or close,
                    close=close,
                    volume=_f(row.get("Volume")) or 0.0,
                )
            )
        if not bars:
            return None
        return PriceHistory(symbol=symbol.strip().upper(), bars=bars, source=self.name)

    async def get_history(
        self, symbol: str, period: str = "3mo", interval: str = "1d"
    ) -> PriceHistory | None:
        try:
            return await self._with_timeout(
                asyncio.to_thread(self._blocking_history, symbol, period, interval),
                self._settings.provider_timeout_seconds * 2,
                f"history {symbol}",
            )
        except Exception as exc:
            log.warning("yfinance_history_failed", symbol=symbol, error=str(exc)[:160])
            return None

    async def health(self) -> dict[str, object]:
        try:
            quote = await self.get_quote("NIFTY50")
            return {"provider": self.name, "ok": quote is not None, "synthetic": False}
        except Exception:
            return {"provider": self.name, "ok": False, "synthetic": False}

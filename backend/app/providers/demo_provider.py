"""Deterministic demo provider.

Mandatory per spec: the entire product must be demonstrable with no market
credentials and no internet. Everything here is a pure function of
(symbol, step), so the same step always yields the same prices - which is
what makes a scripted "leave and come back" demo reproducible.

Data produced here is ALWAYS flagged synthetic and quality=SYNTHETIC.
It must never be presented as live market data.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from app.core.market_time import IST
from app.models.domain import MarketObservation, OHLCBar, PriceHistory, utcnow
from app.models.enums import DataQuality, ProviderName
from app.providers.base import MarketDataProvider
from app.providers.symbols import display_name

# Baseline prices, roughly realistic but explicitly fictional.
BASE_PRICES: dict[str, float] = {
    "TCS": 3150.0,
    "INFY": 1560.0,
    "WIPRO": 245.0,
    "HCLTECH": 1480.0,
    "TECHM": 1290.0,
    "RELIANCE": 1305.0,
    "ONGC": 245.0,
    "NTPC": 355.0,
    "TATAPOWER": 395.0,
    "HDFCBANK": 1690.0,
    "ICICIBANK": 1245.0,
    "SBIN": 815.0,
    "KOTAKBANK": 1755.0,
    "AXISBANK": 1105.0,
    "BAJFINANCE": 6980.0,
    "HINDUNILVR": 2410.0,
    "ITC": 445.0,
    "NESTLEIND": 2280.0,
    "BRITANNIA": 5120.0,
    "MARUTI": 11250.0,
    "TATAMOTORS": 985.0,
    "M&M": 2870.0,
    "BAJAJ-AUTO": 9150.0,
    "SUNPHARMA": 1720.0,
    "DRREDDY": 1285.0,
    "CIPLA": 1495.0,
    "TATASTEEL": 148.0,
    "JSWSTEEL": 985.0,
    "HINDALCO": 645.0,
    "COALINDIA": 415.0,
    "BHARTIARTL": 1595.0,
    "LT": 3620.0,
    "ULTRACEMCO": 11450.0,
    "ASIANPAINT": 2380.0,
    "TITAN": 3390.0,
    "ETERNAL": 322.0,
    "DMART": 3720.0,
    "ADANIENT": 2450.0,
    "PAYTM": 890.0,
    "DLF": 785.0,
    "NIFTY50": 23900.0,
    "NIFTYIT": 30700.0,
    "NIFTYFMCG": 45900.0,
    "NIFTYAUTO": 27700.0,
    "NIFTYPHARMA": 26500.0,
    "NIFTYMETAL": 13300.0,
    "NIFTYENERGY": 38000.0,
    "NIFTYREALTY": 908.0,
    "NIFTYFIN": 26050.0,
    "BANKNIFTY": 51400.0,
    "SENSEX": 78600.0,
}

DEFAULT_BASE = 1000.0
BASE_VOLUMES: dict[str, float] = {"NIFTY50": 250_000.0, "BANKNIFTY": 180_000.0, "SENSEX": 120_000.0}
DEFAULT_VOLUME = 2_500_000.0

# Scripted narrative. step 0 = "what the user saw before they left",
# step 1 = "what they come back to". Values are percent moves and volume
# multiples, chosen so each classification branch is exercised.
SCENARIO: dict[int, dict[str, tuple[float, float]]] = {
    # step: {symbol: (price_change_pct, volume_multiple)}
    0: {},  # baseline - everything flat, normal volume
    1: {
        "TCS": (-4.2, 2.8),  # COMPANY_SPECIFIC: big fall, market up, heavy volume
        "RELIANCE": (3.7, 1.9),  # COMPANY_SPECIFIC upside vs flat sector
        "ETERNAL": (2.1, 3.4),  # TECHNICAL: modest move, very unusual volume
        "HDFCBANK": (-1.4, 1.1),  # MARKET/SECTOR driven, in line with banks
        "INFY": (0.3, 0.9),  # NO_MATERIAL_CHANGE
        "NIFTY50": (0.2, 1.0),  # market essentially flat -> isolates TCS
        "BANKNIFTY": (-1.2, 1.0),  # banking sector down -> explains HDFCBANK
        "NIFTYIT": (-0.8, 1.0),  # IT barely moved -> isolates the TCS fall
        "NIFTYFMCG": (0.4, 1.0),
        "NIFTYENERGY": (0.6, 1.0),  # energy up mildly; RELIANCE far outruns it
    },
    2: {
        "TCS": (1.1, 1.3),  # partial recovery
        "SUNPHARMA": (5.6, 3.1),  # new company-specific event
        "TATAMOTORS": (-3.2, 2.2),
        "NIFTY50": (-0.4, 1.0),
    },
}


def _jitter(symbol: str, step: int, scale: float = 0.6) -> float:
    """Deterministic pseudo-noise in [-scale, +scale] from a stable hash."""
    digest = hashlib.sha256(f"{symbol}:{step}".encode()).hexdigest()
    unit = int(digest[:8], 16) / 0xFFFFFFFF  # 0..1
    return (unit * 2 - 1) * scale


class DemoProvider(MarketDataProvider):
    name = ProviderName.DEMO.value
    priority = 10  # lowest: only used when real providers cannot answer
    synthetic = True

    def __init__(self, step: int = 1) -> None:
        self.step = step

    def _base_price(self, symbol: str) -> float:
        return BASE_PRICES.get(symbol.strip().upper(), DEFAULT_BASE)

    def _base_volume(self, symbol: str) -> float:
        return BASE_VOLUMES.get(symbol.strip().upper(), DEFAULT_VOLUME)

    def _move(self, symbol: str, step: int) -> tuple[float, float]:
        """(change_pct, volume_multiple) for a symbol at a step."""
        scripted = SCENARIO.get(step, {}).get(symbol.strip().upper())
        if scripted:
            return scripted
        return (_jitter(symbol, step, 0.6), 1.0 + abs(_jitter(symbol, step, 0.25)))

    def _observation(self, symbol: str, step: int, observed_at: datetime) -> MarketObservation:
        symbol = symbol.strip().upper()
        change_pct, vol_mult = self._move(symbol, step)
        prev_close = round(self._base_price(symbol), 2)
        price = round(prev_close * (1 + change_pct / 100), 2)
        volume = round(self._base_volume(symbol) * vol_mult)

        spread = abs(change_pct) / 100 * 0.4 + 0.004
        high = round(max(price, prev_close) * (1 + spread), 2)
        low = round(min(price, prev_close) * (1 - spread), 2)

        return MarketObservation(
            symbol=symbol,
            observed_at=observed_at,
            received_at=utcnow(),
            source=self.name,
            source_timestamp=observed_at,
            price=price,
            open=prev_close,
            high=high,
            low=low,
            close=price,
            previous_close=prev_close,
            volume=float(volume),
            change_pct=round(change_pct, 4),
            quality=DataQuality.SYNTHETIC,
            is_synthetic=True,
            notes=[f"Demo data (step {step}) - not real market data"],
        )

    async def get_quote(self, symbol: str) -> MarketObservation | None:
        return self._observation(symbol, self.step, utcnow())

    async def get_batch_quotes(self, symbols: list[str]) -> dict[str, MarketObservation]:
        now = utcnow()
        return {s.strip().upper(): self._observation(s, self.step, now) for s in symbols}

    async def get_history(
        self, symbol: str, period: str = "3mo", interval: str = "1d"
    ) -> PriceHistory | None:
        """Deterministic daily bars ending at the current step's price.

        Volatility is stable and modest so the change engine's "expected daily
        move" baseline is well-defined, which makes the scripted -4.2% on TCS
        register as genuinely abnormal rather than routine.
        """
        symbol = symbol.strip().upper()
        days = {"1mo": 22, "3mo": 66, "6mo": 130, "1y": 252}.get(period, 66)
        base = self._base_price(symbol)
        bars: list[OHLCBar] = []
        today = datetime.now(IST).replace(hour=15, minute=30, second=0, microsecond=0)

        price = base * 0.94  # drift upward into the baseline
        for i in range(days):
            day = today - timedelta(days=days - i)
            if day.weekday() >= 5:
                continue
            # ~1.4% realised daily volatility, in line with a real NSE large cap.
            wiggle = _jitter(f"{symbol}-hist", i, 2.4)
            price = max(price * (1 + wiggle / 100), 1.0)
            close = round(price, 2)
            openp = round(close * (1 - wiggle / 200), 2)
            bars.append(
                OHLCBar(
                    timestamp=day.astimezone(UTC),
                    open=openp,
                    high=round(max(openp, close) * 1.004, 2),
                    low=round(min(openp, close) * 0.996, 2),
                    close=close,
                    volume=self._base_volume(symbol) * (1 + abs(_jitter(symbol, i, 0.3))),
                )
            )
        return PriceHistory(symbol=symbol, bars=bars, source=self.name, is_synthetic=True)

    async def health(self) -> dict[str, object]:
        return {"provider": self.name, "ok": True, "synthetic": True, "step": self.step}

    def describe_scenario(self) -> list[dict[str, object]]:
        """Human-readable script for the current step (used by demo tooling)."""
        return [
            {"symbol": s, "name": display_name(s), "change_pct": c, "volume_multiple": v}
            for s, (c, v) in SCENARIO.get(self.step, {}).items()
        ]

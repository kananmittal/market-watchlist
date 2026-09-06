"""Statistical primitives for the change engine.

Deliberately lightweight and deterministic - no trained model. Every number
produced here must be explainable in one sentence to a user, because it will
be shown to them as evidence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise

from app.models.domain import OHLCBar

# Floor for expected daily move. Without it, a symbol that happened to trade
# flat for weeks would make any move look infinitely abnormal.
MIN_EXPECTED_MOVE_PCT = 0.35
DEFAULT_EXPECTED_MOVE_PCT = 1.5


def pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return round((current - previous) / previous * 100, 4)


def daily_returns(bars: list[OHLCBar]) -> list[float]:
    """Close-to-close percentage returns."""
    out: list[float] = []
    for prev, cur in pairwise(bars):
        if prev.close:
            out.append((cur.close - prev.close) / prev.close * 100)
    return out


def stdev(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(var)


def average_true_range_pct(bars: list[OHLCBar], period: int = 14) -> float | None:
    """ATR as a percentage of price - a volatility measure that, unlike close-to-close
    standard deviation, accounts for intraday range and gaps."""
    if len(bars) < 2:
        return None
    trs: list[float] = []
    for prev, cur in pairwise(bars):
        tr = max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close))
        if cur.close:
            trs.append(tr / cur.close * 100)
    if not trs:
        return None
    window = trs[-period:]
    return round(sum(window) / len(window), 4)


@dataclass
class VolatilityBaseline:
    """How much this symbol normally moves in a day, and where that came from."""

    expected_daily_move_pct: float
    method: str  # "nse_published" | "stdev" | "atr" | "default"
    sample_size: int

    @property
    def is_estimated(self) -> bool:
        return self.method == "default"


def expected_daily_move(
    bars: list[OHLCBar],
    *,
    nse_daily_volatility_pct: float | None = None,
    lookback: int = 30,
) -> VolatilityBaseline:
    """Estimate a symbol's normal daily movement.

    Preference order:
      1. NSE's own published daily volatility (exchange-computed, most credible)
      2. standard deviation of recent daily returns
      3. ATR as a percentage
      4. a conservative default
    """
    if nse_daily_volatility_pct and nse_daily_volatility_pct > 0:
        return VolatilityBaseline(
            max(round(nse_daily_volatility_pct, 4), MIN_EXPECTED_MOVE_PCT), "nse_published", 0
        )

    returns = daily_returns(bars)[-lookback:]
    if len(returns) >= 10:
        sd = stdev(returns)
        if sd > 0:
            return VolatilityBaseline(max(round(sd, 4), MIN_EXPECTED_MOVE_PCT), "stdev", len(returns))

    atr = average_true_range_pct(bars)
    if atr and atr > 0:
        return VolatilityBaseline(max(atr, MIN_EXPECTED_MOVE_PCT), "atr", len(bars))

    return VolatilityBaseline(DEFAULT_EXPECTED_MOVE_PCT, "default", len(bars))


def normalized_move(return_pct: float | None, expected_move_pct: float) -> float | None:
    """|return| / expected daily move.

    1.0 means "a completely typical day". 3.0 means "three times the size of a
    normal day for this stock", which is what makes the signal comparable
    across a volatile small cap and a steady large cap.
    """
    if return_pct is None or expected_move_pct <= 0:
        return None
    return round(abs(return_pct) / expected_move_pct, 4)


@dataclass
class VolumeBaseline:
    average_volume: float
    sample_size: int


def average_volume(bars: list[OHLCBar], lookback: int = 20) -> VolumeBaseline | None:
    vols = [b.volume for b in bars[-lookback:] if b.volume and b.volume > 0]
    if len(vols) < 3:
        return None
    return VolumeBaseline(sum(vols) / len(vols), len(vols))


def volume_multiple(current_volume: float | None, baseline: VolumeBaseline | None) -> float | None:
    if current_volume is None or baseline is None or baseline.average_volume <= 0:
        return None
    return round(current_volume / baseline.average_volume, 4)


def saturating_score(value: float | None, breakpoints: list[tuple[float, float]]) -> float:
    """Piecewise-linear score with saturation.

    `breakpoints` is an ascending list of (input, output) pairs. Values below
    the first point score 0; values above the last saturate at its output.
    Linear interpolation keeps scores smooth, so a stock at 1.99x volume is
    not scored dramatically differently from one at 2.01x.
    """
    if value is None:
        return 0.0
    if not breakpoints:
        return 0.0
    first_in, _ = breakpoints[0]
    if value <= first_in:
        return 0.0
    for (x0, y0), (x1, y1) in pairwise(breakpoints):
        if value <= x1:
            if x1 == x0:
                return y1
            ratio = (value - x0) / (x1 - x0)
            return round(y0 + ratio * (y1 - y0), 4)
    return breakpoints[-1][1]

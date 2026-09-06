"""Indian market session awareness.

Deliberately small and replaceable: it models the common NSE schedule
(Mon-Fri, 09:15-15:30 IST) plus a configurable holiday list. It exists so
the product never describes a Friday-close -> Monday-open gap as
continuous trading.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from enum import StrEnum

IST = timezone(timedelta(hours=5, minutes=30), name="IST")

MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
PRE_OPEN_START = time(9, 0)

# NSE trading holidays. Kept as a simple replaceable set; a missing holiday
# degrades to "market appears open but no ticks", which the freshness layer
# already handles.
NSE_HOLIDAYS_2026: set[date] = {
    date(2026, 1, 26),  # Republic Day
    date(2026, 3, 4),  # Holi
    date(2026, 3, 21),  # Id-ul-Fitr
    date(2026, 4, 1),  # Ram Navami
    date(2026, 4, 3),  # Good Friday
    date(2026, 4, 14),  # Dr. Ambedkar Jayanti
    date(2026, 5, 1),  # Maharashtra Day
    date(2026, 8, 15),  # Independence Day
    date(2026, 10, 2),  # Gandhi Jayanti
    date(2026, 11, 10),  # Diwali (approx.)
    date(2026, 12, 25),  # Christmas
}


class MarketStatus(StrEnum):
    OPEN = "OPEN"
    PRE_OPEN = "PRE_OPEN"
    CLOSED = "CLOSED"
    WEEKEND = "WEEKEND"
    HOLIDAY = "HOLIDAY"


@dataclass(frozen=True)
class MarketState:
    status: MarketStatus
    as_of: datetime
    label: str
    next_open: datetime | None
    last_close: datetime | None

    @property
    def is_open(self) -> bool:
        return self.status is MarketStatus.OPEN


def to_ist(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(IST)


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in NSE_HOLIDAYS_2026


def _combine(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=IST)


def previous_trading_day(d: date) -> date:
    cur = d - timedelta(days=1)
    for _ in range(15):
        if is_trading_day(cur):
            return cur
        cur -= timedelta(days=1)
    return cur


def next_trading_day(d: date) -> date:
    cur = d + timedelta(days=1)
    for _ in range(15):
        if is_trading_day(cur):
            return cur
        cur += timedelta(days=1)
    return cur


def get_market_state(now: datetime | None = None) -> MarketState:
    now_ist = to_ist(now or datetime.now(UTC))
    today = now_ist.date()
    clock = now_ist.time()

    if not is_trading_day(today):
        status = MarketStatus.HOLIDAY if today.weekday() < 5 else MarketStatus.WEEKEND
        prev = previous_trading_day(today)
        nxt = next_trading_day(today)
        label = "Market closed - holiday" if status is MarketStatus.HOLIDAY else "Market closed - weekend"
        return MarketState(status, now_ist, label, _combine(nxt, MARKET_OPEN), _combine(prev, MARKET_CLOSE))

    if PRE_OPEN_START <= clock < MARKET_OPEN:
        return MarketState(
            MarketStatus.PRE_OPEN,
            now_ist,
            "Pre-open session",
            _combine(today, MARKET_OPEN),
            _combine(previous_trading_day(today), MARKET_CLOSE),
        )

    if MARKET_OPEN <= clock <= MARKET_CLOSE:
        return MarketState(
            MarketStatus.OPEN,
            now_ist,
            "Market open",
            None,
            _combine(previous_trading_day(today), MARKET_CLOSE),
        )

    if clock < PRE_OPEN_START:
        # Early morning, before pre-open: the last close was yesterday.
        prev = previous_trading_day(today)
        return MarketState(
            MarketStatus.CLOSED,
            now_ist,
            "Market closed",
            _combine(today, MARKET_OPEN),
            _combine(prev, MARKET_CLOSE),
        )

    # After close today.
    return MarketState(
        MarketStatus.CLOSED,
        now_ist,
        "Market closed",
        _combine(next_trading_day(today), MARKET_OPEN),
        _combine(today, MARKET_CLOSE),
    )


def trading_days_between(start: datetime, end: datetime) -> int:
    """Count trading sessions spanned, so gaps are described honestly."""
    s, e = to_ist(start).date(), to_ist(end).date()
    if e < s:
        return 0
    return sum(1 for i in range((e - s).days + 1) if is_trading_day(s + timedelta(days=i)))


def describe_gap(since: datetime, until: datetime | None = None) -> str:
    """Human phrasing for 'since you last looked', session-aware."""
    end = to_ist(until or datetime.now(UTC))
    start = to_ist(since)
    delta = end - start
    secs = max(delta.total_seconds(), 0)

    if secs < 60:
        return "moments ago"
    if secs < 3600:
        m = int(secs // 60)
        return f"{m} minute{'s' if m != 1 else ''} ago"
    if secs < 86400:
        h = int(secs // 3600)
        base = f"{h} hour{'s' if h != 1 else ''} ago"
    else:
        d = int(secs // 86400)
        base = f"{d} day{'s' if d != 1 else ''} ago"

    sessions = trading_days_between(start, end)
    if sessions == 0:
        return f"{base} (no trading sessions since)"
    return base

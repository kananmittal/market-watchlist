"""User memory: what this person has seen, and what they appear to care about.

Kept strictly separate from market truth. Market observations are global and
shared; everything here is per-user. Duplicating market snapshots per user
would not scale past a handful of accounts.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.core.logging import get_logger
from app.models.domain import ActivityEvent, UserSymbolState, utcnow
from app.models.enums import ActivityType
from app.repositories.changes import ChangeEventRepository
from app.repositories.users import ActivityRepository, UserSymbolStateRepository

log = get_logger("service.user_memory")

#: Activity kinds that signal genuine interest, and their relative weight.
INTEREST_WEIGHTS: dict[ActivityType, float] = {
    ActivityType.STOCK_VIEWED: 1.0,
    ActivityType.CHART_VIEWED: 1.2,
    ActivityType.NEWS_VIEWED: 1.3,
    ActivityType.COPILOT_QUERY: 2.0,
    ActivityType.CHANGE_VIEWED: 1.1,
    ActivityType.CHANGE_ACKNOWLEDGED: 1.5,
    ActivityType.STOCK_SEARCHED: 0.6,
    ActivityType.STOCK_ADDED: 1.4,
}

#: Views older than this contribute nothing; interest should decay.
INTEREST_WINDOW_DAYS = 30
#: Weighted activity at which interest saturates at 1.0.
INTEREST_SATURATION = 12.0


class UserMemoryService:
    def __init__(self) -> None:
        self.state_repo = UserSymbolStateRepository()
        self.activity_repo = ActivityRepository()
        self.change_repo = ChangeEventRepository()

    # ---------------- activity ----------------
    async def log(
        self,
        user_id: str,
        event_type: ActivityType,
        *,
        symbol: str | None = None,
        metadata: dict | None = None,
    ) -> ActivityEvent:
        return await self.activity_repo.log(user_id, event_type, symbol=symbol, metadata=metadata)

    async def recent_activity(
        self, user_id: str, *, symbol: str | None = None, limit: int = 50
    ) -> list[ActivityEvent]:
        return await self.activity_repo.recent(user_id, symbol=symbol, limit=limit)

    # ---------------- view / acknowledge semantics ----------------
    async def record_view(self, user_id: str, symbol: str) -> UserSymbolState:
        """Opening a stock. Advances last_viewed_at and moves any NEW change to
        VIEWED - but explicitly does NOT acknowledge it. Loading a page is not
        the same as saying "I have dealt with this"."""
        symbol = symbol.strip().upper()
        state = await self.state_repo.mark_viewed(user_id, symbol)
        await self.change_repo.mark_symbol_viewed(user_id, symbol)
        await self.log(user_id, ActivityType.STOCK_VIEWED, symbol=symbol)
        return state

    async def acknowledge(self, user_id: str, symbol: str) -> UserSymbolState:
        """An explicit "I have reviewed this" from the user."""
        symbol = symbol.strip().upper()
        state = await self.state_repo.mark_acknowledged(user_id, symbol)
        await self.log(user_id, ActivityType.CHANGE_ACKNOWLEDGED, symbol=symbol)
        return state

    async def ensure_tracked(self, user_id: str, symbol: str) -> UserSymbolState:
        return await self.state_repo.ensure(user_id, symbol.strip().upper())

    async def forget_symbol(self, user_id: str, symbol: str) -> None:
        symbol = symbol.strip().upper()
        await self.state_repo.delete(user_id, symbol)
        await self.change_repo.delete_for_symbol(user_id, symbol)

    # ---------------- interest scoring ----------------
    def _decay(self, age_days: float) -> float:
        """Linear decay across the window: today counts fully, day 30 counts nothing."""
        return max(0.0, 1.0 - (age_days / INTEREST_WINDOW_DAYS))

    async def recompute_interest(self, user_id: str, symbols: list[str]) -> dict[str, float]:
        """Recompute bounded interest scores from the activity log.

        One query for all activity, then scoring in memory - not a query per
        symbol. Scores are clamped to 0-1; the change engine converts that into
        at most 15 additive points and can never change severity.
        """
        if not symbols:
            return {}
        wanted = {s.strip().upper() for s in symbols}
        cutoff = utcnow() - timedelta(days=INTEREST_WINDOW_DAYS)

        events = await self.activity_repo.recent(user_id, limit=1000)
        totals: dict[str, float] = dict.fromkeys(wanted, 0.0)
        for ev in events:
            if not ev.symbol or ev.symbol not in wanted:
                continue
            created = ev.created_at
            if created < cutoff:
                continue
            weight = INTEREST_WEIGHTS.get(ev.event_type, 0.4)
            age_days = (utcnow() - created).total_seconds() / 86_400
            totals[ev.symbol] += weight * self._decay(age_days)

        scores = {sym: round(min(total / INTEREST_SATURATION, 1.0), 4) for sym, total in totals.items()}
        for sym, score in scores.items():
            if score > 0:
                await self.state_repo.set_interest(user_id, sym, score)
        return scores

    # ---------------- reference points ----------------
    async def reference_points(
        self, user_id: str, symbols: list[str], fallback: datetime
    ) -> dict[str, datetime]:
        """The "since" anchor per symbol.

        Prefers when the user last actually looked at that stock, so a symbol
        they never opened keeps accumulating change rather than being silently
        reset by a dashboard load.
        """
        states = await self.state_repo.get_many(user_id, [s.strip().upper() for s in symbols])
        out: dict[str, datetime] = {}
        for sym in symbols:
            key = sym.strip().upper()
            state = states.get(key)
            if state and state.last_viewed_at:
                # They actually opened this stock: measure from then.
                out[key] = state.last_viewed_at
            elif state and state.first_added_at:
                # Never opened. Measure from when they added it, NOT from the last
                # dashboard load - the dashboard anchor moves on every visit, which
                # would give each symbol a new "since" and create a duplicate change
                # event per load.
                out[key] = state.first_added_at
            else:
                out[key] = fallback
        return out

    async def states_for(self, user_id: str, symbols: list[str]) -> dict[str, UserSymbolState]:
        return await self.state_repo.get_many(user_id, [s.strip().upper() for s in symbols])

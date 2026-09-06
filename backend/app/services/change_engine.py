"""The meaningful-change engine.

Answers "what changed since this user last looked, and does it matter?"

Design commitments:
  * Meaningful change is NOT a fixed price threshold. A 2% move in a placid
    large cap and a 2% move in a volatile small cap are different events.
  * Scoring is deterministic and fully decomposed. Every point is attributable
    to a named component and rendered as user-visible evidence.
  * User relevance influences ranking but never manufactures severity. Severity
    is derived from base significance only, so a stock you check often cannot
    become HIGH on a nothing day.
  * The engine works with no news and no LLM. Those enrich it; they do not
    gate it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.core.config import get_settings
from app.models.domain import (
    ChangeEvent,
    ChangeMetrics,
    Evidence,
    MarketObservation,
    NewsEvent,
    OHLCBar,
    ScoreBreakdown,
    UserSymbolState,
    utcnow,
)
from app.models.enums import (
    ChangeStatus,
    ChangeType,
    DataQuality,
    EvidenceType,
    PrimaryReason,
    Severity,
)
from app.providers.symbols import display_name
from app.services.analytics import (
    VolatilityBaseline,
    average_volume,
    expected_daily_move,
    normalized_move,
    pct_change,
    saturating_score,
    volume_multiple,
)

# ---- component maxima (sum of base = 85, + up to 15 user = 100) ----
MAX_ABNORMALITY = 25.0
MAX_RELATIVE = 20.0
MAX_VOLUME = 15.0
MAX_NEWS = 25.0
MAX_USER = 15.0

# ---- severity thresholds, applied to BASE significance only ----
HIGH_THRESHOLD = 52.0
MEDIUM_THRESHOLD = 24.0
MATERIAL_THRESHOLD = 16.0

# ---- classification tuning ----
#: A move counts as "explained by" an index if the index accounts for at least
#: this fraction of it.
EXPLAINED_FRACTION = 0.6
#: Divergence from benchmark, in multiples of a normal day, that marks a move
#: as idiosyncratic rather than market-driven.
DIVERGENCE_SIGNIFICANT = 1.2
#: Divergence so large that the move is company-specific even with no news to
#: point at. Below this, an unexplained move is reported as TECHNICAL, because
#: without evidence of an event we should not assert a company cause.
DIVERGENCE_STRONG = 2.5

ABNORMALITY_CURVE = [(0.8, 0.0), (1.5, 8.0), (2.5, 17.0), (3.5, 22.0), (5.0, MAX_ABNORMALITY)]
RELATIVE_CURVE = [(0.5, 0.0), (1.2, 7.0), (2.0, 13.0), (3.0, 17.5), (4.5, MAX_RELATIVE)]
NEWS_CURVE = [(0.1, 0.0), (0.35, 7.0), (0.6, 14.0), (0.8, 19.0), (1.0, 21.0)]


@dataclass
class ChangeInput:
    """Everything needed to judge one symbol for one user."""

    symbol: str
    user_id: str
    since: datetime
    current: MarketObservation | None
    baseline: MarketObservation | None = None  # what the user last saw
    benchmark: MarketObservation | None = None
    sector: MarketObservation | None = None
    sector_name: str | None = None
    history: list[OHLCBar] = field(default_factory=list)
    news: list[NewsEvent] = field(default_factory=list)
    user_state: UserSymbolState | None = None
    nse_daily_volatility_pct: float | None = None


class ChangeEngine:
    def __init__(self) -> None:
        self.settings = get_settings()

    # ------------------------------------------------------------------
    # component scores
    # ------------------------------------------------------------------
    def _score_abnormality(self, norm_move: float | None) -> float:
        return min(saturating_score(norm_move, ABNORMALITY_CURVE), MAX_ABNORMALITY)

    def _score_relative(self, divergence_norm: float | None) -> float:
        return min(saturating_score(divergence_norm, RELATIVE_CURVE), MAX_RELATIVE)

    def _score_volume(self, multiple: float | None) -> float:
        s = self.settings
        curve = [
            (1.0, 0.0),
            (s.volume_noteworthy_multiple, 4.0),
            (s.volume_significant_multiple, 8.5),
            (s.volume_unusual_multiple, 12.5),
            (s.volume_unusual_multiple * 1.8, MAX_VOLUME),
        ]
        return min(saturating_score(multiple, curve), MAX_VOLUME)

    def _score_news(self, news: list[NewsEvent]) -> tuple[float, float, int]:
        """Score by the single most significant event, plus a small bonus for
        genuinely distinct additional events. Three articles about one story are
        already collapsed upstream, so they cannot triple-count here."""
        if not news:
            return 0.0, 0.0, 0
        weighted = sorted((n.weighted_significance for n in news), reverse=True)
        top = weighted[0]
        score = saturating_score(top, NEWS_CURVE)
        extra = sum(1 for w in weighted[1:] if w >= 0.35)
        score += min(extra * 2.0, 4.0)
        return min(score, MAX_NEWS), top, len(news)

    def _score_user(self, state: UserSymbolState | None, base: float) -> float:
        """Bounded ADDITIVE adjustment.

        Additive, never multiplicative: multiplying would let a favourite stock
        turn noise into an emergency. Additionally the adjustment is damped when
        base significance is very low, so a quiet day stays quiet.
        """
        if state is None:
            return 0.0
        interest = max(0.0, min(1.0, state.interest_score))
        raw = interest * MAX_USER
        if base < MATERIAL_THRESHOLD:
            raw *= 0.5
        return round(min(raw, MAX_USER), 4)

    # ------------------------------------------------------------------
    # classification
    # ------------------------------------------------------------------
    def _classify(
        self,
        *,
        base: float,
        move_pct: float | None,
        benchmark_pct: float | None,
        sector_pct: float | None,
        divergence_norm: float | None,
        news_score: float,
        volume_score: float,
    ) -> tuple[ChangeType, PrimaryReason]:
        if base < MATERIAL_THRESHOLD or move_pct is None:
            return ChangeType.NO_MATERIAL_CHANGE, PrimaryReason.NO_SIGNAL

        def explained_by(index_pct: float | None) -> bool:
            """True when the index moved the same way and accounts for most of the move."""
            if index_pct is None or move_pct == 0:
                return False
            if (index_pct >= 0) != (move_pct >= 0):
                return False
            return abs(index_pct) >= abs(move_pct) * EXPLAINED_FRACTION

        diverges = (divergence_norm or 0) >= DIVERGENCE_SIGNIFICANT

        # A real company event plus divergence from the market is the clearest
        # company-specific signal available.
        if news_score >= 10.0 and diverges:
            return ChangeType.COMPANY_SPECIFIC, PrimaryReason.COMPANY_EVENT
        if explained_by(sector_pct) and not diverges:
            return ChangeType.SECTOR_DRIVEN, PrimaryReason.SECTOR_MOVE
        if explained_by(benchmark_pct) and not diverges:
            return ChangeType.MARKET_DRIVEN, PrimaryReason.MARKET_MOVE
        if news_score >= 10.0:
            return ChangeType.COMPANY_SPECIFIC, PrimaryReason.COMPANY_EVENT
        # A very large idiosyncratic move is company-specific on its own terms:
        # neither the market nor the sector explains it.
        if (divergence_norm or 0) >= DIVERGENCE_STRONG:
            return ChangeType.COMPANY_SPECIFIC, PrimaryReason.BENCHMARK_DIVERGENCE
        # No news, but abnormal trading behaviour: report it as TECHNICAL rather
        # than asserting a company cause we have no evidence for.
        if volume_score >= 8.0:
            return ChangeType.TECHNICAL, PrimaryReason.VOLUME_SPIKE
        if diverges:
            return ChangeType.COMPANY_SPECIFIC, PrimaryReason.BENCHMARK_DIVERGENCE
        return ChangeType.TECHNICAL, PrimaryReason.ABNORMAL_MOVE

    def _severity(self, base: float) -> Severity:
        if base >= HIGH_THRESHOLD:
            return Severity.HIGH
        if base >= MEDIUM_THRESHOLD:
            return Severity.MEDIUM
        return Severity.NORMAL

    # ------------------------------------------------------------------
    # evaluation
    # ------------------------------------------------------------------
    def evaluate(self, data: ChangeInput) -> ChangeEvent:
        symbol = data.symbol.strip().upper()
        current = data.current

        if current is None or current.price is None:
            return self._unavailable(data, symbol)

        # --- movement since the user's own reference point ---
        baseline_price = data.baseline.price if data.baseline else None
        if baseline_price:
            move_pct = pct_change(current.price, baseline_price)
            move_basis = "since you last looked"
        else:
            move_pct = current.change_pct
            move_basis = "in the latest session"

        # --- volatility baseline ---
        vol: VolatilityBaseline = expected_daily_move(
            data.history, nse_daily_volatility_pct=data.nse_daily_volatility_pct
        )
        norm_move = normalized_move(move_pct, vol.expected_daily_move_pct)

        # --- benchmark / sector ---
        benchmark_pct = self._index_move(data.benchmark, data.baseline, data.symbol)
        sector_pct = self._index_move(data.sector, None, data.symbol)
        rel_benchmark = (
            round(move_pct - benchmark_pct, 4) if move_pct is not None and benchmark_pct is not None else None
        )
        rel_sector = (
            round(move_pct - sector_pct, 4) if move_pct is not None and sector_pct is not None else None
        )
        divergence_norm = (
            round(abs(rel_benchmark) / vol.expected_daily_move_pct, 4) if rel_benchmark is not None else None
        )

        # --- volume ---
        vol_baseline = average_volume(data.history)
        vol_multiple = volume_multiple(current.volume, vol_baseline)

        # --- component scores ---
        s_abn = self._score_abnormality(norm_move)
        s_rel = self._score_relative(divergence_norm)
        s_vol = self._score_volume(vol_multiple)
        s_news, top_news_sig, news_count = self._score_news(data.news)
        base = round(s_abn + s_rel + s_vol + s_news, 4)
        s_user = self._score_user(data.user_state, base)
        total = round(min(base + s_user, 100.0), 2)

        change_type, reason = self._classify(
            base=base,
            move_pct=move_pct,
            benchmark_pct=benchmark_pct,
            sector_pct=sector_pct,
            divergence_norm=divergence_norm,
            news_score=s_news,
            volume_score=s_vol,
        )
        severity = Severity.NORMAL if change_type is ChangeType.NO_MATERIAL_CHANGE else self._severity(base)

        metrics = ChangeMetrics(
            price_change_pct=move_pct,
            relative_to_benchmark_pct=rel_benchmark,
            relative_to_sector_pct=rel_sector,
            volume_multiple=vol_multiple,
            normalized_move=norm_move,
            expected_daily_move_pct=vol.expected_daily_move_pct,
            news_event_count=news_count,
            max_news_significance=round(top_news_sig, 4),
        )
        breakdown = ScoreBreakdown(
            abnormality=round(s_abn, 2),
            relative_move=round(s_rel, 2),
            volume=round(s_vol, 2),
            news=round(s_news, 2),
            base_significance=round(base, 2),
            user_adjustment=round(s_user, 2),
            total=total,
        )
        evidence = self._build_evidence(
            data=data,
            current=current,
            move_pct=move_pct,
            move_basis=move_basis,
            vol=vol,
            norm_move=norm_move,
            benchmark_pct=benchmark_pct,
            sector_pct=sector_pct,
            rel_benchmark=rel_benchmark,
            vol_multiple=vol_multiple,
            vol_baseline=vol_baseline,
            breakdown=breakdown,
        )

        return ChangeEvent(
            id=self._change_id(data.user_id, symbol, data.since),
            user_id=data.user_id,
            symbol=symbol,
            since=data.since,
            detected_at=utcnow(),
            change_type=change_type,
            severity=severity,
            attention_score=total,
            primary_reason=reason,
            status=ChangeStatus.NEW
            if change_type is not ChangeType.NO_MATERIAL_CHANGE
            else ChangeStatus.VIEWED,
            metrics=metrics,
            breakdown=breakdown,
            evidence=evidence,
            headline=self._headline(symbol, move_pct, move_basis, change_type, reason),
            data_quality=current.quality,
            is_synthetic=current.is_synthetic,
        )

    # ------------------------------------------------------------------
    def _index_move(
        self, index_obs: MarketObservation | None, user_baseline: MarketObservation | None, symbol: str
    ) -> float | None:
        """Index move over the comparable window.

        Uses the index's own session change. Comparing a stock's since-you-last-
        looked move against an index's single-session move is imperfect, but it
        is the honest approximation available without storing an index baseline
        per user, and the UI states which window each figure covers.
        """
        if index_obs is None:
            return None
        return index_obs.change_pct

    def _change_id(self, user_id: str, symbol: str, since: datetime) -> str:
        import hashlib

        raw = f"{user_id}:{symbol}:{since.isoformat()}"
        return f"chg_{hashlib.sha256(raw.encode()).hexdigest()[:16]}"

    def _headline(
        self, symbol: str, move_pct: float | None, basis: str, change_type: ChangeType, reason: PrimaryReason
    ) -> str:
        name = display_name(symbol)
        if move_pct is None:
            return f"{name}: no current price available"
        direction = "up" if move_pct >= 0 else "down"
        head = f"{name} {direction} {abs(move_pct):.1f}% {basis}"
        tail = {
            ChangeType.COMPANY_SPECIFIC: "company-specific",
            ChangeType.SECTOR_DRIVEN: "moving with its sector",
            ChangeType.MARKET_DRIVEN: "moving with the market",
            ChangeType.TECHNICAL: "unusual trading activity",
            ChangeType.NO_MATERIAL_CHANGE: "nothing material",
        }[change_type]
        return f"{head} - {tail}"

    def _unavailable(self, data: ChangeInput, symbol: str) -> ChangeEvent:
        return ChangeEvent(
            id=self._change_id(data.user_id, symbol, data.since),
            user_id=data.user_id,
            symbol=symbol,
            since=data.since,
            change_type=ChangeType.NO_MATERIAL_CHANGE,
            severity=Severity.NORMAL,
            attention_score=0.0,
            primary_reason=PrimaryReason.NO_SIGNAL,
            status=ChangeStatus.VIEWED,
            data_quality=DataQuality.UNAVAILABLE,
            headline=f"{display_name(symbol)}: price data unavailable",
            evidence=[
                Evidence(
                    evidence_type=EvidenceType.DATA_QUALITY,
                    label="No price data available from any provider",
                    source_ref="providers",
                )
            ],
        )

    # ------------------------------------------------------------------
    def _build_evidence(self, **kw) -> list[Evidence]:
        """Turn the numbers into checkable statements.

        Ordered by how much each contributed, so the strongest reason is read
        first. A score without these is a product bug.
        """
        data: ChangeInput = kw["data"]
        current: MarketObservation = kw["current"]
        move_pct = kw["move_pct"]
        vol: VolatilityBaseline = kw["vol"]
        norm_move = kw["norm_move"]
        bd: ScoreBreakdown = kw["breakdown"]
        items: list[Evidence] = []

        if move_pct is not None:
            direction = "rose" if move_pct >= 0 else "fell"
            items.append(
                Evidence(
                    evidence_type=EvidenceType.PRICE_MOVE,
                    label=f"Price {direction} {abs(move_pct):.2f}% {kw['move_basis']}",
                    value=round(move_pct, 4),
                    unit="%",
                    source_ref=current.source,
                    weight_contribution=bd.abnormality,
                )
            )

        if norm_move is not None:
            descriptor = (
                "about a normal day"
                if norm_move < 1.3
                else "roughly twice a normal day"
                if norm_move < 2.2
                else f"{norm_move:.1f}x a normal day"
            )
            items.append(
                Evidence(
                    evidence_type=EvidenceType.ABNORMALITY,
                    label=(
                        f"Typical daily movement is +/-{vol.expected_daily_move_pct:.2f}%; "
                        f"this is {descriptor}"
                    ),
                    value=norm_move,
                    unit="x",
                    source_ref=f"volatility:{vol.method}",
                    weight_contribution=bd.abnormality,
                    metadata={"method": vol.method, "sample_size": vol.sample_size},
                )
            )

        if kw["benchmark_pct"] is not None:
            bpct = kw["benchmark_pct"]
            label = f"NIFTY 50 is {'up' if bpct >= 0 else 'down'} {abs(bpct):.2f}%"
            if kw["rel_benchmark"] is not None:
                gap = kw["rel_benchmark"]
                label += f" - {'outperforming' if gap >= 0 else 'underperforming'} by {abs(gap):.2f} points"
            items.append(
                Evidence(
                    evidence_type=EvidenceType.BENCHMARK,
                    label=label,
                    value=round(bpct, 4),
                    unit="%",
                    source_ref="NIFTY50",
                    weight_contribution=bd.relative_move,
                )
            )

        if kw["sector_pct"] is not None:
            spct = kw["sector_pct"]
            items.append(
                Evidence(
                    evidence_type=EvidenceType.SECTOR,
                    label=(
                        f"{data.sector_name or 'Sector index'} is "
                        f"{'up' if spct >= 0 else 'down'} {abs(spct):.2f}%"
                    ),
                    value=round(spct, 4),
                    unit="%",
                    source_ref=data.sector_name,
                    weight_contribution=0.0,
                )
            )

        vm = kw["vol_multiple"]
        if vm is not None:
            vb = kw["vol_baseline"]
            if vm >= self.settings.volume_unusual_multiple:
                qualifier = "highly unusual"
            elif vm >= self.settings.volume_significant_multiple:
                qualifier = "significant"
            elif vm >= self.settings.volume_noteworthy_multiple:
                qualifier = "noteworthy"
            else:
                qualifier = "normal"
            items.append(
                Evidence(
                    evidence_type=EvidenceType.VOLUME,
                    label=f"Volume is {vm:.1f}x its recent average ({qualifier})",
                    value=vm,
                    unit="x",
                    source_ref=f"avg_of_{vb.sample_size}_sessions" if vb else None,
                    weight_contribution=bd.volume,
                )
            )

        for item in data.news[:3]:
            items.append(
                Evidence(
                    evidence_type=EvidenceType.NEWS,
                    label=item.headline[:180],
                    value=item.weighted_significance,
                    unit="significance",
                    source_ref=item.source,
                    weight_contribution=bd.news,
                    metadata={
                        "event_type": item.event_type.value,
                        "published_at": item.published_at.isoformat(),
                        "url": item.source_url,
                        "article_count": item.article_count,
                    },
                )
            )

        state = data.user_state
        if state and bd.user_adjustment > 0:
            items.append(
                Evidence(
                    evidence_type=EvidenceType.USER_CONTEXT,
                    label=(
                        f"You view this stock often (interest {state.interest_score:.0%}) - "
                        f"raised its ranking, not its severity"
                    ),
                    value=bd.user_adjustment,
                    unit="points",
                    weight_contribution=bd.user_adjustment,
                )
            )

        if current.quality is DataQuality.CONFLICTED:
            items.append(
                Evidence(
                    evidence_type=EvidenceType.DATA_QUALITY,
                    label="Providers disagree on this price - value under verification",
                    source_ref="conflict",
                )
            )
        if current.is_synthetic:
            items.append(
                Evidence(
                    evidence_type=EvidenceType.DATA_QUALITY,
                    label="Demo data - not real market data",
                    source_ref="demo",
                )
            )
        return items

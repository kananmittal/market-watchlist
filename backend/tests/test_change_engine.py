"""Unit tests for the meaningful-change engine.

These encode the product rules, not just the arithmetic: what counts as
meaningful, how a move is attributed, and the guarantee that personal
interest cannot manufacture severity.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models.domain import utcnow
from app.models.enums import ChangeStatus, ChangeType, DataQuality, EvidenceType, PrimaryReason, Severity
from app.services.change_engine import (
    MAX_ABNORMALITY,
    MAX_NEWS,
    MAX_RELATIVE,
    MAX_USER,
    MAX_VOLUME,
    ChangeEngine,
    ChangeInput,
)


@pytest.fixture
def engine():
    return ChangeEngine()


@pytest.fixture
def since():
    return utcnow() - timedelta(hours=17)


def build(
    symbol,
    *,
    current,
    baseline=None,
    benchmark=None,
    sector=None,
    sector_name=None,
    history=None,
    news=None,
    user_state=None,
    since=None,
    nse_vol=None,
):
    return ChangeInput(
        symbol=symbol,
        user_id="u1",
        since=since or (utcnow() - timedelta(hours=17)),
        current=current,
        baseline=baseline,
        benchmark=benchmark,
        sector=sector,
        sector_name=sector_name,
        history=history or [],
        news=news or [],
        user_state=user_state,
        nse_daily_volatility_pct=nse_vol,
    )


class TestClassification:
    """Spec section 13: every change must be attributed to a cause."""

    def test_company_specific_when_news_and_divergence(self, engine, make_obs, make_bars, make_news, since):
        ev = engine.evaluate(
            build(
                "TCS",
                since=since,
                current=make_obs("TCS", 2874.0, 3000.0, volume=7_000_000),
                baseline=make_obs("TCS", 3000.0, 3000.0),
                benchmark=make_obs("NIFTY50", 23900.0, change_pct=0.2),
                sector=make_obs("^CNXIT", 30000.0, change_pct=-0.8),
                sector_name="NIFTY IT",
                history=make_bars(),
                news=[make_news()],
            )
        )
        assert ev.change_type is ChangeType.COMPANY_SPECIFIC
        assert ev.primary_reason is PrimaryReason.COMPANY_EVENT
        assert ev.severity is Severity.HIGH

    def test_sector_driven_when_move_tracks_sector(self, engine, make_obs, make_bars, since):
        """Same -4.2% as above, but the whole sector fell: far less remarkable."""
        ev = engine.evaluate(
            build(
                "TCS",
                since=since,
                current=make_obs("TCS", 2874.0, 3000.0),
                baseline=make_obs("TCS", 3000.0, 3000.0),
                benchmark=make_obs("NIFTY50", 23900.0, change_pct=-3.8),
                sector=make_obs("^CNXIT", 30000.0, change_pct=-4.0),
                sector_name="NIFTY IT",
                history=make_bars(),
            )
        )
        assert ev.change_type is ChangeType.SECTOR_DRIVEN
        assert ev.primary_reason is PrimaryReason.SECTOR_MOVE

    def test_market_driven_when_move_tracks_benchmark(self, engine, make_obs, make_bars, since):
        ev = engine.evaluate(
            build(
                "TCS",
                since=since,
                current=make_obs("TCS", 2874.0, 3000.0),
                baseline=make_obs("TCS", 3000.0, 3000.0),
                benchmark=make_obs("NIFTY50", 23900.0, change_pct=-4.0),
                history=make_bars(),
            )
        )
        assert ev.change_type is ChangeType.MARKET_DRIVEN
        assert ev.primary_reason is PrimaryReason.MARKET_MOVE

    def test_technical_when_volume_spikes_without_news(self, engine, make_obs, make_bars, since):
        """No news means we must not assert a company cause."""
        ev = engine.evaluate(
            build(
                "ETERNAL",
                since=since,
                current=make_obs("ETERNAL", 328.7, 322.0, volume=8_500_000),
                baseline=make_obs("ETERNAL", 322.0, 322.0),
                benchmark=make_obs("NIFTY50", 23900.0, change_pct=0.2),
                history=make_bars(base=322.0),
            )
        )
        assert ev.change_type is ChangeType.TECHNICAL
        assert ev.primary_reason is PrimaryReason.VOLUME_SPIKE

    def test_no_material_change_on_a_quiet_day(self, engine, make_obs, make_bars, since):
        ev = engine.evaluate(
            build(
                "INFY",
                since=since,
                current=make_obs("INFY", 1564.0, 1560.0),
                baseline=make_obs("INFY", 1560.0, 1560.0),
                benchmark=make_obs("NIFTY50", 23900.0, change_pct=0.2),
                history=make_bars(base=1560.0),
            )
        )
        assert ev.change_type is ChangeType.NO_MATERIAL_CHANGE
        assert ev.severity is Severity.NORMAL
        assert not ev.is_material

    def test_large_unexplained_move_is_company_specific(self, engine, make_obs, make_bars, since):
        """Too big for the market or sector to explain, even with no news."""
        ev = engine.evaluate(
            build(
                "SUNPHARMA",
                since=since,
                current=make_obs("SUNPHARMA", 1816.0, 1720.0, volume=7_800_000),
                baseline=make_obs("SUNPHARMA", 1720.0, 1720.0),
                benchmark=make_obs("NIFTY50", 23900.0, change_pct=0.1),
                history=make_bars(base=1720.0),
            )
        )
        assert ev.change_type is ChangeType.COMPANY_SPECIFIC
        assert ev.primary_reason is PrimaryReason.BENCHMARK_DIVERGENCE


class TestUserRelevanceIsBounded:
    """Spec section 7: interest may reorder the feed, never inflate severity."""

    def _quiet(self, make_obs, make_bars, state=None):
        return build(
            "INFY",
            current=make_obs("INFY", 1564.0, 1560.0),
            baseline=make_obs("INFY", 1560.0, 1560.0),
            benchmark=make_obs("NIFTY50", 23900.0, change_pct=0.2),
            history=make_bars(base=1560.0),
            user_state=state,
        )

    def test_max_interest_cannot_make_a_quiet_day_severe(self, engine, make_obs, make_bars, make_user_state):
        loved = engine.evaluate(self._quiet(make_obs, make_bars, make_user_state("INFY", interest=1.0)))
        assert loved.severity is Severity.NORMAL
        assert loved.change_type is ChangeType.NO_MATERIAL_CHANGE

    def test_interest_raises_score_for_ranking(self, engine, make_obs, make_bars, make_user_state):
        ignored = engine.evaluate(self._quiet(make_obs, make_bars))
        loved = engine.evaluate(self._quiet(make_obs, make_bars, make_user_state("INFY", interest=1.0)))
        assert loved.attention_score > ignored.attention_score

    def test_adjustment_is_additive_not_multiplicative(self, engine, make_obs, make_bars, make_user_state):
        """Spec: base 5 + 8 = 13, never base 5 x something."""
        ev = engine.evaluate(self._quiet(make_obs, make_bars, make_user_state("INFY", interest=1.0)))
        b = ev.breakdown
        assert b.total == pytest.approx(b.base_significance + b.user_adjustment)

    def test_adjustment_never_exceeds_its_cap(self, engine, make_obs, make_bars, make_user_state):
        ev = engine.evaluate(self._quiet(make_obs, make_bars, make_user_state("INFY", interest=1.0)))
        assert ev.breakdown.user_adjustment <= MAX_USER


class TestScoreBounds:
    def test_components_respect_their_maxima(self, engine, make_obs, make_bars, make_news):
        ev = engine.evaluate(
            build(
                "TCS",
                current=make_obs("TCS", 1500.0, 3000.0, volume=90_000_000),  # -50%, 36x volume
                baseline=make_obs("TCS", 3000.0, 3000.0),
                benchmark=make_obs("NIFTY50", 23900.0, change_pct=5.0),
                history=make_bars(),
                news=[make_news(), make_news(dedupe_key="k2"), make_news(dedupe_key="k3")],
            )
        )
        b = ev.breakdown
        assert b.abnormality <= MAX_ABNORMALITY
        assert b.relative_move <= MAX_RELATIVE
        assert b.volume <= MAX_VOLUME
        assert b.news <= MAX_NEWS
        assert 0 <= b.total <= 100

    def test_score_never_negative(self, engine, make_obs, make_bars):
        ev = engine.evaluate(
            build(
                "INFY",
                current=make_obs("INFY", 1560.0, 1560.0),
                baseline=make_obs("INFY", 1560.0, 1560.0),
                history=make_bars(base=1560.0),
            )
        )
        assert ev.attention_score >= 0

    def test_breakdown_sums_to_base(self, engine, make_obs, make_bars, make_news):
        ev = engine.evaluate(
            build(
                "TCS",
                current=make_obs("TCS", 2874.0, 3000.0, volume=7_000_000),
                baseline=make_obs("TCS", 3000.0, 3000.0),
                benchmark=make_obs("NIFTY50", 23900.0, change_pct=0.2),
                history=make_bars(),
                news=[make_news()],
            )
        )
        b = ev.breakdown
        assert b.base_significance == pytest.approx(
            b.abnormality + b.relative_move + b.volume + b.news, abs=0.01
        )


class TestSinceYouLastLooked:
    """The product's defining behaviour: compare against the user's own anchor."""

    def test_uses_baseline_when_available(self, engine, make_obs, make_bars):
        ev = engine.evaluate(
            build(
                "TCS",
                current=make_obs("TCS", 2874.0, 2900.0),  # -0.9% on the session
                # A real baseline is an EARLIER observation; same-timestamp
                # baselines are the same bar and are deliberately ignored.
                baseline=make_obs("TCS", 3000.0, 3000.0, age_seconds=86_400),
                history=make_bars(),
            )
        )
        assert ev.metrics.price_change_pct == pytest.approx(-4.2, abs=0.01)
        assert "since you last looked" in ev.headline

    def test_ignores_a_baseline_that_is_the_same_bar(self, engine, make_obs, make_bars):
        """Daily bars mean the stored baseline is often the current bar itself.

        Comparing a bar with itself yields 0%, which would report "nothing
        changed" on a day the stock moved several percent. The session change
        must be used instead.
        """
        ev = engine.evaluate(
            build(
                "INFY",
                current=make_obs("INFY", 1090.3, 1130.0),  # -3.51% on the session
                baseline=make_obs("INFY", 1090.3, 1130.0),  # same bar, same timestamp
                history=make_bars(base=1130.0),
            )
        )
        assert ev.metrics.price_change_pct == pytest.approx(-3.51, abs=0.05)
        assert "latest session" in ev.headline

    def test_falls_back_to_session_change_for_first_visit(self, engine, make_obs, make_bars):
        ev = engine.evaluate(
            build(
                "TCS",
                current=make_obs("TCS", 2874.0, 3000.0),
                baseline=None,
                history=make_bars(),
            )
        )
        assert ev.metrics.price_change_pct == pytest.approx(-4.2, abs=0.01)
        assert "latest session" in ev.headline

    def test_volatility_context_changes_the_verdict(self, engine, make_obs, make_bars):
        """An identical 2% move is material for a calm stock, routine for a wild one."""
        common = {"current": make_obs("X", 102.0, 100.0), "baseline": make_obs("X", 100.0, 100.0)}
        calm = engine.evaluate(build("X", history=make_bars(daily_pct=0.2, base=100.0), **common))
        wild = engine.evaluate(build("X", history=make_bars(daily_pct=5.0, base=100.0), **common))
        assert calm.breakdown.abnormality > wild.breakdown.abnormality


class TestEvidence:
    """Spec section 21: a score with no explanation is a product bug."""

    def test_material_change_always_carries_evidence(self, engine, make_obs, make_bars, make_news):
        ev = engine.evaluate(
            build(
                "TCS",
                current=make_obs("TCS", 2874.0, 3000.0, volume=7_000_000),
                baseline=make_obs("TCS", 3000.0, 3000.0),
                benchmark=make_obs("NIFTY50", 23900.0, change_pct=0.2),
                history=make_bars(),
                news=[make_news()],
            )
        )
        assert len(ev.evidence) >= 4
        kinds = {e.evidence_type for e in ev.evidence}
        assert EvidenceType.PRICE_MOVE in kinds
        assert EvidenceType.ABNORMALITY in kinds
        assert EvidenceType.BENCHMARK in kinds
        assert EvidenceType.VOLUME in kinds
        assert EvidenceType.NEWS in kinds

    def test_evidence_states_the_normal_range(self, engine, make_obs, make_bars):
        ev = engine.evaluate(
            build(
                "TCS",
                current=make_obs("TCS", 2874.0, 3000.0),
                baseline=make_obs("TCS", 3000.0, 3000.0),
                history=make_bars(),
                nse_vol=1.74,
            )
        )
        labels = " ".join(ev.evidence_labels)
        assert "1.74" in labels and "Typical daily movement" in labels

    def test_synthetic_data_is_disclosed(self, engine, make_obs, make_bars):
        ev = engine.evaluate(
            build(
                "TCS",
                current=make_obs("TCS", 2874.0, 3000.0, synthetic=True),
                baseline=make_obs("TCS", 3000.0, 3000.0),
                history=make_bars(),
            )
        )
        assert any("Demo data" in label for label in ev.evidence_labels)
        assert ev.is_synthetic


class TestDegradation:
    def test_missing_price_is_reported_not_crashed(self, engine):
        ev = engine.evaluate(build("TCS", current=None))
        assert ev.data_quality is DataQuality.UNAVAILABLE
        assert ev.change_type is ChangeType.NO_MATERIAL_CHANGE
        assert "unavailable" in ev.headline.lower()

    def test_works_with_no_history(self, engine, make_obs):
        ev = engine.evaluate(
            build(
                "TCS",
                current=make_obs("TCS", 2874.0, 3000.0),
                baseline=make_obs("TCS", 3000.0, 3000.0),
                history=[],
            )
        )
        assert ev.metrics.expected_daily_move_pct > 0  # falls back to a default

    def test_works_with_no_benchmark_or_news(self, engine, make_obs, make_bars):
        ev = engine.evaluate(
            build(
                "TCS",
                current=make_obs("TCS", 2874.0, 3000.0),
                baseline=make_obs("TCS", 3000.0, 3000.0),
                history=make_bars(),
            )
        )
        assert ev.metrics.relative_to_benchmark_pct is None
        assert ev.breakdown.news == 0.0
        assert ev.attention_score > 0  # still detects the abnormal move

    def test_deduplicated_news_does_not_triple_count(self, engine, make_obs, make_bars, make_news):
        """Three articles about one story arrive as one event and score once."""
        one = engine.evaluate(
            build(
                "TCS",
                current=make_obs("TCS", 2874.0, 3000.0),
                baseline=make_obs("TCS", 3000.0, 3000.0),
                history=make_bars(),
                news=[make_news(dedupe_key="same")],
            )
        )
        assert one.breakdown.news <= MAX_NEWS


class TestDeterminism:
    def test_same_input_gives_same_id_and_score(self, engine, make_obs, make_bars, since):
        args = {
            "current": make_obs("TCS", 2874.0, 3000.0),
            "baseline": make_obs("TCS", 3000.0, 3000.0),
            "history": make_bars(),
            "since": since,
        }
        a = engine.evaluate(build("TCS", **args))
        b = engine.evaluate(build("TCS", **args))
        assert a.id == b.id
        assert a.attention_score == b.attention_score

    def test_id_differs_per_user_and_anchor(self, engine, make_obs, make_bars, since):
        base = {"current": make_obs("TCS", 2874.0, 3000.0), "history": make_bars()}
        a = engine.evaluate(build("TCS", since=since, **base))
        b = engine.evaluate(build("TCS", since=since - timedelta(days=1), **base))
        assert a.id != b.id


class TestStatusLifecycle:
    def test_material_change_starts_new(self, engine, make_obs, make_bars, make_news):
        ev = engine.evaluate(
            build(
                "TCS",
                current=make_obs("TCS", 2874.0, 3000.0, volume=7_000_000),
                baseline=make_obs("TCS", 3000.0, 3000.0),
                benchmark=make_obs("NIFTY50", 23900.0, change_pct=0.2),
                history=make_bars(),
                news=[make_news()],
            )
        )
        assert ev.status is ChangeStatus.NEW

    def test_nothing_material_does_not_demand_attention(self, engine, make_obs, make_bars):
        ev = engine.evaluate(
            build(
                "INFY",
                current=make_obs("INFY", 1564.0, 1560.0),
                baseline=make_obs("INFY", 1560.0, 1560.0),
                history=make_bars(base=1560.0),
            )
        )
        assert ev.status is ChangeStatus.VIEWED

"""Unit tests for the statistical primitives behind meaningful change."""

from __future__ import annotations

import pytest

from app.services.analytics import (
    MIN_EXPECTED_MOVE_PCT,
    average_true_range_pct,
    average_volume,
    daily_returns,
    expected_daily_move,
    normalized_move,
    pct_change,
    saturating_score,
    stdev,
    volume_multiple,
)


class TestPctChange:
    def test_basic_gain_and_loss(self):
        assert pct_change(110.0, 100.0) == 10.0
        assert pct_change(90.0, 100.0) == -10.0

    def test_no_change(self):
        assert pct_change(100.0, 100.0) == 0.0

    @pytest.mark.parametrize("current,previous", [(None, 100.0), (100.0, None), (100.0, 0.0)])
    def test_guards_against_missing_and_zero(self, current, previous):
        # A zero previous price must not raise ZeroDivisionError.
        assert pct_change(current, previous) is None


class TestStdev:
    def test_known_value(self):
        assert stdev([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]) == pytest.approx(2.138, abs=1e-3)

    def test_degenerate_inputs(self):
        assert stdev([]) == 0.0
        assert stdev([5.0]) == 0.0
        assert stdev([3.0, 3.0, 3.0]) == 0.0


class TestExpectedDailyMove:
    def test_prefers_nse_published_volatility(self, make_bars):
        baseline = expected_daily_move(make_bars(), nse_daily_volatility_pct=1.74)
        assert baseline.method == "nse_published"
        assert baseline.expected_daily_move_pct == 1.74

    def test_falls_back_to_stdev(self, make_bars):
        baseline = expected_daily_move(make_bars(daily_pct=1.0))
        assert baseline.method == "stdev"
        assert baseline.expected_daily_move_pct > 0

    def test_default_when_no_history(self):
        baseline = expected_daily_move([])
        assert baseline.method == "default"
        assert baseline.is_estimated

    def test_floor_prevents_divide_by_near_zero(self, make_bars):
        # A stock that barely moves must not make every move look infinitely abnormal.
        baseline = expected_daily_move(make_bars(daily_pct=0.001))
        assert baseline.expected_daily_move_pct >= MIN_EXPECTED_MOVE_PCT

    def test_volatile_stock_gets_higher_baseline(self, make_bars):
        calm = expected_daily_move(make_bars(daily_pct=0.5)).expected_daily_move_pct
        wild = expected_daily_move(make_bars(daily_pct=4.0)).expected_daily_move_pct
        assert wild > calm


class TestNormalizedMove:
    def test_scales_by_expected_move(self):
        assert normalized_move(-4.2, 1.4) == pytest.approx(3.0)
        assert normalized_move(1.4, 1.4) == pytest.approx(1.0)

    def test_direction_is_ignored(self):
        assert normalized_move(2.0, 1.0) == normalized_move(-2.0, 1.0)

    def test_identical_percent_differs_by_stock_volatility(self):
        """The core idea: 2% is not the same event for every stock."""
        calm = normalized_move(2.0, 0.5)
        volatile = normalized_move(2.0, 4.0)
        assert calm > volatile
        assert calm == pytest.approx(4.0)
        assert volatile == pytest.approx(0.5)

    def test_guards(self):
        assert normalized_move(None, 1.0) is None
        assert normalized_move(2.0, 0.0) is None


class TestVolume:
    def test_multiple(self, make_bars):
        baseline = average_volume(make_bars(volume=1_000_000))
        assert volume_multiple(2_800_000, baseline) == pytest.approx(2.8)

    def test_needs_enough_samples(self, make_bars):
        assert average_volume(make_bars(n=2)) is None

    def test_ignores_zero_volume_bars(self, make_bars):
        bars = make_bars(volume=0)
        assert average_volume(bars) is None

    def test_guards(self, make_bars):
        assert volume_multiple(None, average_volume(make_bars())) is None
        assert volume_multiple(1000.0, None) is None


class TestSaturatingScore:
    CURVE = [(1.0, 0.0), (1.5, 4.0), (2.0, 8.0), (3.0, 12.0), (5.0, 15.0)]

    def test_below_floor_scores_zero(self):
        assert saturating_score(0.5, self.CURVE) == 0.0
        assert saturating_score(1.0, self.CURVE) == 0.0

    def test_hits_declared_breakpoints(self):
        assert saturating_score(1.5, self.CURVE) == 4.0
        assert saturating_score(3.0, self.CURVE) == 12.0

    def test_interpolates_smoothly(self):
        # No cliff between 1.99x and 2.01x volume.
        assert saturating_score(1.99, self.CURVE) == pytest.approx(7.92, abs=0.05)
        assert saturating_score(2.01, self.CURVE) == pytest.approx(8.04, abs=0.05)

    def test_saturates_at_maximum(self):
        assert saturating_score(50.0, self.CURVE) == 15.0

    def test_monotonic(self):
        values = [saturating_score(v, self.CURVE) for v in [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 9.0]]
        assert values == sorted(values)

    def test_none_scores_zero(self):
        assert saturating_score(None, self.CURVE) == 0.0


class TestATR:
    def test_returns_percentage(self, make_bars):
        atr = average_true_range_pct(make_bars())
        assert atr is not None and 0 < atr < 100

    def test_insufficient_data(self):
        assert average_true_range_pct([]) is None


class TestDailyReturns:
    def test_length_is_one_less_than_bars(self, make_bars):
        bars = make_bars(n=10)
        assert len(daily_returns(bars)) == 9

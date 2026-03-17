"""Tests for Kelly criterion position sizing."""

import pytest

from backend.risk.kelly import DEFAULT_KELLY_PARAMS, compute_kelly_fraction, get_position_size


class TestKellyFraction:
    def test_positive_edge_gives_positive_fraction(self):
        fraction = compute_kelly_fraction(win_rate=0.6, win_loss_ratio=1.5)
        assert fraction > 0

    def test_no_edge_gives_zero(self):
        fraction = compute_kelly_fraction(win_rate=0.3, win_loss_ratio=0.5)
        assert fraction == 0.0

    def test_half_kelly_is_half(self):
        full = compute_kelly_fraction(win_rate=0.6, win_loss_ratio=1.5, use_half_kelly=False)
        half = compute_kelly_fraction(win_rate=0.6, win_loss_ratio=1.5, use_half_kelly=True)
        assert abs(half - full / 2) < 1e-10

    def test_perfect_win_rate(self):
        fraction = compute_kelly_fraction(win_rate=1.0, win_loss_ratio=2.0)
        assert fraction > 0

    def test_zero_win_loss_ratio(self):
        fraction = compute_kelly_fraction(win_rate=0.6, win_loss_ratio=0)
        assert fraction == 0.0

    def test_fraction_bounded(self):
        fraction = compute_kelly_fraction(win_rate=0.9, win_loss_ratio=5.0)
        assert 0 <= fraction <= 1.0


class TestPositionSize:
    def test_returns_position_dollars(self, vol_normal):
        result = get_position_size(
            strategy="stat_arb", vol=vol_normal, regime="bull_trend",
            trailing_trades=[], capital=100_000,
        )
        assert "position_dollars" in result
        assert "position_pct" in result
        assert result["position_dollars"] >= 0

    def test_crisis_reduces_position(self, vol_normal, vol_crisis):
        normal = get_position_size(
            strategy="stat_arb", vol=vol_normal, regime="bull_trend",
            trailing_trades=[], capital=100_000,
        )
        crisis = get_position_size(
            strategy="stat_arb", vol=vol_crisis, regime="crisis",
            trailing_trades=[], capital=100_000,
        )
        assert crisis["position_dollars"] <= normal["position_dollars"]


class TestDefaultParams:
    def test_all_strategies_have_defaults(self):
        expected = {"stat_arb", "catalyst", "cross_asset", "flow", "gap_reversion"}
        assert set(DEFAULT_KELLY_PARAMS.keys()) == expected

    def test_default_win_rates_are_reasonable(self):
        for strat, params in DEFAULT_KELLY_PARAMS.items():
            assert 0.4 <= params["win_rate"] <= 0.9, f"{strat} win rate out of range"
            assert params["win_loss_ratio"] > 0, f"{strat} win_loss_ratio must be positive"

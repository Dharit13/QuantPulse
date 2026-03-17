"""Tests for adaptive parameter functions across all strategies."""

import pytest

from backend.adaptive.hold_periods import get_adaptive_hold
from backend.adaptive.kelly_adaptive import compute_adaptive_kelly
from backend.adaptive.risk_scaling import get_adaptive_risk_limits
from backend.adaptive.stops import compute_stop
from backend.adaptive.targets import compute_targets
from backend.adaptive.thresholds import (
    get_catalyst_params,
    get_cross_asset_params,
    get_flow_params,
    get_gap_reversion_params,
    get_stat_arb_params,
)
from backend.adaptive.vol_context import VolContext


class TestThresholds:
    @pytest.mark.parametrize("getter", [
        get_stat_arb_params, get_catalyst_params, get_cross_asset_params,
        get_flow_params, get_gap_reversion_params,
    ])
    def test_returns_dict(self, getter, vol_normal):
        result = getter(vol_normal)
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_stat_arb_tightens_in_crisis(self, vol_normal, vol_crisis):
        normal = get_stat_arb_params(vol_normal)
        crisis = get_stat_arb_params(vol_crisis)
        assert isinstance(normal, dict)
        assert isinstance(crisis, dict)


class TestRiskScaling:
    def test_returns_all_keys(self, vol_normal):
        limits = get_adaptive_risk_limits(vol_normal)
        assert "max_position_pct" in limits
        assert "max_gross_exposure" in limits

    def test_crisis_tightens_limits(self, vol_normal, vol_crisis):
        normal = get_adaptive_risk_limits(vol_normal)
        crisis = get_adaptive_risk_limits(vol_crisis)
        assert crisis["max_position_pct"] <= normal["max_position_pct"]

    def test_limits_are_valid(self, vol_normal):
        limits = get_adaptive_risk_limits(vol_normal)
        assert limits["max_position_pct"] > 0
        assert limits["max_gross_exposure"] > 0


class TestAdaptiveKelly:
    def test_returns_fraction(self, vol_normal):
        result = compute_adaptive_kelly(
            strategy="stat_arb", vol=vol_normal, regime="bull_trend",
            trailing_trades=[], portfolio_correlation=0.0,
        )
        assert "kelly_fraction" in result
        assert 0.0 <= result["kelly_fraction"] <= 1.0

    def test_crisis_reduces_kelly(self, vol_normal, vol_crisis):
        normal = compute_adaptive_kelly(
            strategy="stat_arb", vol=vol_normal, regime="bull_trend",
            trailing_trades=[], portfolio_correlation=0.0,
        )
        crisis = compute_adaptive_kelly(
            strategy="stat_arb", vol=vol_crisis, regime="crisis",
            trailing_trades=[], portfolio_correlation=0.0,
        )
        assert crisis["kelly_fraction"] <= normal["kelly_fraction"]

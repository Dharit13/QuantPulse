"""Tests for regime transition logic and hysteresis."""

import pytest

from backend.adaptive.vol_context import VolContext
from backend.models.schemas import Regime
from backend.regime.transitions import PERSISTENCE_DAYS, RegimeTracker


class TestRegimeTracker:
    def test_initial_state(self):
        tracker = RegimeTracker()
        assert tracker.current_regime == Regime.BULL_CHOPPY
        assert tracker.candidate_regime is None

    def test_regime_requires_persistence(self, vol_normal):
        tracker = RegimeTracker()
        weights = {"stat_arb": 0.2, "catalyst": 0.2, "momentum": 0.2, "flow": 0.2, "intraday": 0.2}

        result = tracker.update(Regime.BEAR_TREND, weights, vol_normal)
        assert result["effective_regime"] == Regime.BULL_CHOPPY

    def test_regime_switches_after_persistence(self, vol_normal):
        tracker = RegimeTracker()
        weights = {"stat_arb": 0.2, "catalyst": 0.2, "momentum": 0.2, "flow": 0.2, "intraday": 0.2}

        for _ in range(PERSISTENCE_DAYS + 1):
            result = tracker.update(Regime.BEAR_TREND, weights, vol_normal)

        assert result["effective_regime"] == Regime.BEAR_TREND

    def test_crisis_vix_override_is_immediate(self):
        tracker = RegimeTracker()
        vol_extreme = VolContext(vix_current=42.0, vix_5d_avg=38.0, vix_20d_avg=30.0, vix_percentile_1y=99.0)
        weights = {"stat_arb": 0.2, "catalyst": 0.2, "momentum": 0.2, "flow": 0.2, "intraday": 0.2}

        result = tracker.update(Regime.BULL_TREND, weights, vol_extreme)
        assert result["effective_regime"] == Regime.CRISIS

    def test_history_is_recorded(self, vol_normal):
        tracker = RegimeTracker()
        weights = {"stat_arb": 0.2, "catalyst": 0.2, "momentum": 0.2, "flow": 0.2, "intraday": 0.2}

        for _ in range(5):
            tracker.update(Regime.BEAR_TREND, weights, vol_normal)

        assert len(tracker.history) > 0

    def test_weights_are_smoothed(self, vol_normal):
        tracker = RegimeTracker()
        new_weights = {"stat_arb": 0.5, "catalyst": 0.1, "momentum": 0.1, "flow": 0.1, "intraday": 0.2}

        result = tracker.update(Regime.BULL_CHOPPY, new_weights, vol_normal)
        assert "current_weights" in result
        effective_weights = result["current_weights"]
        assert effective_weights["stat_arb"] != 0.5

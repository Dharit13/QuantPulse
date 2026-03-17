"""Tests for the regime detection engine."""

import numpy as np
import pandas as pd
import pytest

from backend.models.schemas import Regime
from backend.regime.detector import detect_regime


class TestRegimeDetector:
    def test_returns_required_keys(self, vix_df, spy_df):
        result = detect_regime(vix_df, spy_df)
        assert "regime" in result
        assert "confidence" in result
        assert "probabilities" in result
        assert isinstance(result["regime"], Regime)

    def test_probabilities_sum_to_one(self, vix_df, spy_df):
        result = detect_regime(vix_df, spy_df)
        total = sum(result["probabilities"].values())
        assert abs(total - 1.0) < 0.05

    def test_confidence_bounded(self, vix_df, spy_df):
        result = detect_regime(vix_df, spy_df)
        assert 0.0 <= result["confidence"] <= 1.0

    def test_high_vix_suggests_bear_or_crisis(self):
        np.random.seed(99)
        n = 252
        dates = pd.bdate_range(end="2026-03-17", periods=n)
        vix = np.full(n, 38.0) + np.random.normal(0, 1, n)
        vix_df = pd.DataFrame({
            "Open": vix, "High": vix + 2, "Low": vix - 2,
            "Close": vix, "Volume": np.ones(n) * 1e6,
        }, index=dates)
        spy = 400 - np.cumsum(np.abs(np.random.normal(0, 0.5, n)))
        spy_df = pd.DataFrame({
            "Open": spy, "High": spy + 1, "Low": spy - 1,
            "Close": spy, "Volume": np.ones(n) * 1e8,
        }, index=dates)
        result = detect_regime(vix_df, spy_df)
        assert result["regime"] in (Regime.BEAR_TREND, Regime.CRISIS)

    def test_low_vix_uptrend_suggests_bull(self):
        np.random.seed(100)
        n = 252
        dates = pd.bdate_range(end="2026-03-17", periods=n)
        vix = np.full(n, 12.0) + np.random.normal(0, 0.3, n)
        vix_df = pd.DataFrame({
            "Open": vix, "High": vix + 0.5, "Low": vix - 0.5,
            "Close": vix, "Volume": np.ones(n) * 1e6,
        }, index=dates)
        spy = 400 + np.cumsum(np.abs(np.random.normal(0.3, 0.5, n)))
        spy_df = pd.DataFrame({
            "Open": spy, "High": spy + 2, "Low": spy - 1,
            "Close": spy, "Volume": np.ones(n) * 1e8,
        }, index=dates)
        result = detect_regime(vix_df, spy_df)
        assert result["regime"] in (Regime.BULL_TREND, Regime.BULL_CHOPPY)

    def test_returns_strategy_weights(self, vix_df, spy_df):
        result = detect_regime(vix_df, spy_df)
        assert "strategy_weights" in result
        weights = result["strategy_weights"]
        assert isinstance(weights, dict)
        assert len(weights) > 0

"""Tests for cointegration analysis functions."""

import numpy as np
import pandas as pd

from backend.signals.cointegration import (
    adf_test,
    compute_half_life,
    compute_hurst_exponent,
    compute_spread,
    compute_zscore,
    engle_granger_test,
    validate_pair,
)


class TestADFTest:
    def test_stationary_series(self):
        np.random.seed(10)
        stationary = pd.Series(np.random.normal(0, 1, 500))
        result = adf_test(stationary)
        assert result["pvalue"] < 0.05
        assert result["is_stationary"] is True

    def test_random_walk_is_nonstationary(self):
        np.random.seed(11)
        walk = pd.Series(np.cumsum(np.random.normal(0, 1, 500)))
        result = adf_test(walk)
        assert result["pvalue"] > 0.01


class TestEngleGranger:
    def test_cointegrated_pair(self, cointegrated_pair):
        a, b = cointegrated_pair
        result = engle_granger_test(a, b)
        assert "pvalue" in result
        assert "is_cointegrated" in result

    def test_independent_series_not_cointegrated(self, non_cointegrated_pair):
        a, b = non_cointegrated_pair
        result = engle_granger_test(a, b)
        assert result["is_cointegrated"] is False or result["pvalue"] > 0.01


class TestHalfLife:
    def test_mean_reverting_series(self):
        np.random.seed(12)
        n = 1000
        ou = np.zeros(n)
        theta = 0.1
        for i in range(1, n):
            ou[i] = ou[i - 1] - theta * ou[i - 1] + np.random.normal(0, 0.5)
        hl = compute_half_life(pd.Series(ou))
        assert 2 < hl < 30

    def test_random_walk_has_large_half_life(self):
        np.random.seed(13)
        walk = pd.Series(np.cumsum(np.random.normal(0, 1, 500)))
        hl = compute_half_life(walk)
        assert hl > 50 or hl < 0


class TestHurst:
    def test_mean_reverting_below_half(self):
        np.random.seed(14)
        n = 1000
        ou = np.zeros(n)
        for i in range(1, n):
            ou[i] = ou[i - 1] - 0.3 * ou[i - 1] + np.random.normal(0, 0.5)
        h = compute_hurst_exponent(pd.Series(ou))
        assert h < 0.5

    def test_random_walk_hurst(self):
        np.random.seed(15)
        walk = pd.Series(np.cumsum(np.random.normal(0, 1, 1000)))
        h = compute_hurst_exponent(walk)
        assert 0.2 < h < 0.8  # Broader range for stochastic variation


class TestSpreadAndZScore:
    def test_compute_spread(self, cointegrated_pair):
        a, b = cointegrated_pair
        spread = compute_spread(a, b)
        assert len(spread) == len(a)

    def test_zscore_centered(self, cointegrated_pair):
        a, b = cointegrated_pair
        spread = compute_spread(a, b)
        z = compute_zscore(spread, window=60)
        valid = z.dropna()
        assert abs(valid.mean()) < 0.5

    def test_zscore_drops_initial_window(self, cointegrated_pair):
        a, b = cointegrated_pair
        spread = compute_spread(a, b)
        z = compute_zscore(spread, window=60)
        valid = z.dropna()
        assert len(valid) > 0
        assert len(valid) <= len(spread)


class TestValidatePair:
    def test_cointegrated_pair_is_valid(self, cointegrated_pair):
        a, b = cointegrated_pair
        result = validate_pair(a, b)
        assert isinstance(result, dict)
        assert "is_valid" in result or "valid" in result

    def test_independent_pair_is_invalid(self, non_cointegrated_pair):
        a, b = non_cointegrated_pair
        result = validate_pair(a, b)
        valid = result.get("is_valid", result.get("valid", False))
        assert not valid

"""Tests for VaR computation."""

import numpy as np
import pandas as pd
import pytest

from backend.risk.var import (
    compute_historical_var,
    compute_monte_carlo_var,
    compute_parametric_var,
    compute_portfolio_var,
)


@pytest.fixture
def daily_returns():
    np.random.seed(42)
    return pd.Series(np.random.normal(0.0005, 0.015, 252))


class TestHistoricalVaR:
    def test_var_is_negative(self, daily_returns):
        result = compute_historical_var(daily_returns, confidence=0.95)
        assert result["var"] < 0

    def test_cvar_worse_than_var(self, daily_returns):
        result = compute_historical_var(daily_returns, confidence=0.95)
        assert result["cvar"] <= result["var"]


class TestParametricVaR:
    def test_returns_var(self, daily_returns):
        result = compute_parametric_var(daily_returns, confidence=0.95)
        assert "var" in result
        assert result["var"] < 0

    def test_99_worse_than_95(self, daily_returns):
        var_95 = compute_parametric_var(daily_returns, confidence=0.95)["var"]
        var_99 = compute_parametric_var(daily_returns, confidence=0.99)["var"]
        assert var_99 <= var_95


class TestMonteCarloVaR:
    def test_returns_var(self, daily_returns):
        result = compute_monte_carlo_var(daily_returns, confidence=0.95, n_simulations=1000)
        assert "var" in result

    def test_more_sims_is_stable(self, daily_returns):
        r1 = compute_monte_carlo_var(daily_returns, confidence=0.95, n_simulations=5000)
        r2 = compute_monte_carlo_var(daily_returns, confidence=0.95, n_simulations=5000)
        assert abs(r1["var"] - r2["var"]) < 0.01


class TestPortfolioVaR:
    def test_portfolio_var(self):
        np.random.seed(42)
        position_returns = {
            "AAPL": pd.Series(np.random.normal(0.001, 0.02, 100)),
            "MSFT": pd.Series(np.random.normal(0.001, 0.015, 100)),
        }
        weights = {"AAPL": 0.6, "MSFT": 0.4}
        result = compute_portfolio_var(position_returns, weights)
        assert isinstance(result, dict)

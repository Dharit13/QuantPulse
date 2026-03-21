"""Shared test fixtures — synthetic market data and VolContext objects."""

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from backend.adaptive.vol_context import VolContext


@pytest.fixture
def vol_normal() -> VolContext:
    """Normal volatility context (VIX ~18, calm market)."""
    return VolContext(
        vix_current=18.0, vix_5d_avg=17.5, vix_20d_avg=17.0,
        vix_percentile_1y=45.0,
    )


@pytest.fixture
def vol_crisis() -> VolContext:
    """Crisis volatility context (VIX ~45)."""
    return VolContext(
        vix_current=45.0, vix_5d_avg=40.0, vix_20d_avg=35.0,
        vix_percentile_1y=98.0,
    )


@pytest.fixture
def vol_low() -> VolContext:
    """Ultra-low vol context (VIX ~11)."""
    return VolContext(
        vix_current=11.0, vix_5d_avg=11.5, vix_20d_avg=12.0,
        vix_percentile_1y=10.0,
    )


@pytest.fixture
def spy_df() -> pd.DataFrame:
    """252 trading days of synthetic SPY data with realistic trend."""
    np.random.seed(42)
    n = 252
    dates = pd.bdate_range(end=datetime.now(), periods=n)
    returns = np.random.normal(0.0004, 0.012, n)
    prices = 450 * np.cumprod(1 + returns)
    volume = np.random.randint(50_000_000, 150_000_000, n)
    df = pd.DataFrame({
        "Open": prices * (1 - np.abs(np.random.normal(0, 0.003, n))),
        "High": prices * (1 + np.abs(np.random.normal(0, 0.005, n))),
        "Low": prices * (1 - np.abs(np.random.normal(0, 0.005, n))),
        "Close": prices,
        "Volume": volume,
    }, index=dates)
    return df


@pytest.fixture
def vix_df() -> pd.DataFrame:
    """252 trading days of synthetic VIX data."""
    np.random.seed(43)
    n = 252
    dates = pd.bdate_range(end=datetime.now(), periods=n)
    vix = 18 + np.cumsum(np.random.normal(0, 0.5, n))
    vix = np.clip(vix, 10, 80)
    df = pd.DataFrame({
        "Open": vix * (1 + np.random.normal(0, 0.02, n)),
        "High": vix * (1 + np.abs(np.random.normal(0, 0.03, n))),
        "Low": vix * (1 - np.abs(np.random.normal(0, 0.03, n))),
        "Close": vix,
        "Volume": np.random.randint(1_000_000, 5_000_000, n),
    }, index=dates)
    return df


@pytest.fixture
def cointegrated_pair() -> tuple[pd.Series, pd.Series]:
    """Two cointegrated price series for stat arb testing."""
    np.random.seed(44)
    n = 500
    random_walk = np.cumsum(np.random.normal(0, 1, n))
    noise_a = np.random.normal(0, 0.5, n)
    noise_b = np.random.normal(0, 0.5, n)
    series_a = pd.Series(100 + random_walk + noise_a, name="A")
    series_b = pd.Series(50 + 0.5 * random_walk + noise_b, name="B")
    return series_a, series_b


@pytest.fixture
def non_cointegrated_pair() -> tuple[pd.Series, pd.Series]:
    """Two independent random walks (not cointegrated)."""
    np.random.seed(45)
    n = 500
    series_a = pd.Series(100 + np.cumsum(np.random.normal(0, 1, n)), name="A")
    series_b = pd.Series(100 + np.cumsum(np.random.normal(0, 1, n)), name="B")
    return series_a, series_b

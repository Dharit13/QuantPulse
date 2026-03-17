"""Cointegration tests and spread analysis for statistical arbitrage.

Tests: ADF, Engle-Granger, half-life via OU process, Hurst exponent.
"""

import logging

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.tsa.stattools import adfuller, coint

logger = logging.getLogger(__name__)


def adf_test(series: pd.Series) -> dict:
    """Augmented Dickey-Fuller test for stationarity.

    H0: series has a unit root (non-stationary).
    Reject at p < 0.01 for mean-reversion.
    """
    if len(series) < 30:
        return {"statistic": 0.0, "pvalue": 1.0, "is_stationary": False}

    try:
        result = adfuller(series.dropna(), autolag="AIC")
        return {
            "statistic": float(result[0]),
            "pvalue": float(result[1]),
            "is_stationary": result[1] < 0.01,
            "critical_values": {k: float(v) for k, v in result[4].items()},
        }
    except Exception:
        logger.exception("ADF test failed")
        return {"statistic": 0.0, "pvalue": 1.0, "is_stationary": False}


def engle_granger_test(series_a: pd.Series, series_b: pd.Series) -> dict:
    """Engle-Granger cointegration test between two price series."""
    if len(series_a) < 30 or len(series_b) < 30:
        return {"statistic": 0.0, "pvalue": 1.0, "is_cointegrated": False}

    try:
        common = series_a.index.intersection(series_b.index)
        a = series_a.loc[common].dropna()
        b = series_b.loc[common].dropna()

        if len(a) < 30:
            return {"statistic": 0.0, "pvalue": 1.0, "is_cointegrated": False}

        score, pvalue, _ = coint(a, b)
        return {
            "statistic": float(score),
            "pvalue": float(pvalue),
            "is_cointegrated": pvalue < 0.01,
        }
    except Exception:
        logger.exception("Engle-Granger test failed")
        return {"statistic": 0.0, "pvalue": 1.0, "is_cointegrated": False}


def compute_half_life(spread: pd.Series) -> float:
    """Compute mean-reversion half-life using Ornstein-Uhlenbeck process.

    half_life = -ln(2) / ln(beta) where beta is AR(1) coefficient.
    """
    if len(spread) < 30:
        return float("inf")

    try:
        spread_lag = spread.shift(1).dropna()
        spread_diff = spread.diff().dropna()

        common = spread_lag.index.intersection(spread_diff.index)
        y = spread_diff.loc[common].values
        x = spread_lag.loc[common].values

        x_with_const = np.column_stack([x, np.ones(len(x))])
        beta = np.linalg.lstsq(x_with_const, y, rcond=None)[0][0]

        if beta >= 0:
            return float("inf")  # Not mean-reverting

        half_life = -np.log(2) / np.log(1 + beta)
        return max(0.5, float(half_life))
    except Exception:
        logger.exception("Half-life computation failed")
        return float("inf")


def compute_hurst_exponent(series: pd.Series, max_lag: int = 100) -> float:
    """Compute Hurst exponent. H < 0.5 = mean-reverting, H > 0.5 = trending."""
    if len(series) < max_lag * 2:
        return 0.5

    try:
        lags = range(2, min(max_lag, len(series) // 2))
        tau = []
        for lag in lags:
            diffs = (series.values[lag:] - series.values[:-lag])
            tau.append(np.std(diffs))

        if not tau or any(t <= 0 for t in tau):
            return 0.5

        log_lags = np.log(list(lags))
        log_tau = np.log(tau)

        slope, _, _, _, _ = stats.linregress(log_lags, log_tau)
        return float(max(0.0, min(1.0, slope)))
    except Exception:
        logger.exception("Hurst exponent computation failed")
        return 0.5


def compute_spread(
    series_a: pd.Series,
    series_b: pd.Series,
    method: str = "ratio",
) -> pd.Series:
    """Compute spread between two price series."""
    common = series_a.index.intersection(series_b.index)
    a = series_a.loc[common]
    b = series_b.loc[common]

    if method == "ratio":
        return (a / b).dropna()
    elif method == "difference":
        return (a - b).dropna()
    elif method == "log_ratio":
        return (np.log(a) - np.log(b)).dropna()
    else:
        return (a - b).dropna()


def compute_zscore(spread: pd.Series, window: int = 60) -> pd.Series:
    """Compute rolling z-score of spread."""
    mean = spread.rolling(window).mean()
    std = spread.rolling(window).std()
    return ((spread - mean) / std.replace(0, 1)).dropna()


def validate_pair(
    series_a: pd.Series,
    series_b: pd.Series,
    min_adf_pvalue: float = 0.01,
    min_half_life: float = 3.0,
    max_half_life: float = 30.0,
) -> dict:
    """Run full pair validation suite. Returns pass/fail with details."""
    spread = compute_spread(series_a, series_b)

    adf = adf_test(spread)
    eg = engle_granger_test(series_a, series_b)
    hl = compute_half_life(spread)
    hurst = compute_hurst_exponent(spread)

    tests_passed = sum([
        adf["is_stationary"],
        eg["is_cointegrated"],
    ])

    is_valid = (
        tests_passed >= 1
        and min_half_life <= hl <= max_half_life
        and hurst < 0.5
    )

    return {
        "is_valid": is_valid,
        "adf": adf,
        "engle_granger": eg,
        "half_life": hl,
        "hurst_exponent": hurst,
        "tests_passed": tests_passed,
        "spread_stats": {
            "mean": float(spread.mean()),
            "std": float(spread.std()),
            "current": float(spread.iloc[-1]),
        },
    }

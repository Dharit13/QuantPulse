"""Value at Risk computation — Historical, Parametric, and Monte Carlo.

Three VaR methods (spec §20 Math Appendix):
  - Historical VaR: sort returns, take the α-percentile
  - Parametric VaR: assume normal, μ − z_α × σ × √t
  - Monte Carlo VaR: simulate N portfolio paths from bootstrapped returns

All methods produce both VaR (expected loss at confidence level) and CVaR
(expected shortfall = avg loss beyond VaR, a.k.a. Expected Shortfall).

The risk manager uses daily VaR at 95% confidence to enforce the 2% daily
VaR limit (spec §11 Layer 3).

Reference: QUANTPULSE_FINAL_SPEC.md §11, §20
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from backend.adaptive.vol_context import VolContext

logger = logging.getLogger(__name__)

CONFIDENCE_LEVELS = (0.95, 0.99)
Z_SCORES = {0.95: 1.645, 0.99: 2.326}
MC_SIMULATIONS = 10_000
MC_HORIZON_DAYS = 1


def compute_historical_var(
    returns: pd.Series | np.ndarray,
    confidence: float = 0.95,
) -> dict[str, float]:
    """Historical VaR: empirical percentile of return distribution.

    Args:
        returns: daily return series (decimal, e.g. 0.01 = 1%)
        confidence: VaR confidence level (0.95 = 95%)

    Returns:
        {"var": float, "cvar": float, "n_observations": int}
    """
    arr = np.asarray(returns, dtype=float)
    arr = arr[np.isfinite(arr)]

    if len(arr) < 20:
        logger.warning("Insufficient data for historical VaR (%d obs)", len(arr))
        return {"var": 0.0, "cvar": 0.0, "n_observations": len(arr)}

    alpha = 1.0 - confidence
    var = float(np.percentile(arr, alpha * 100))

    tail = arr[arr <= var]
    cvar = float(tail.mean()) if len(tail) > 0 else var

    return {
        "var": round(var, 6),
        "cvar": round(cvar, 6),
        "n_observations": len(arr),
    }


def compute_parametric_var(
    returns: pd.Series | np.ndarray,
    confidence: float = 0.95,
    horizon_days: int = 1,
) -> dict[str, float]:
    """Parametric (Gaussian) VaR: μ − z_α × σ × √t.

    Assumes normal return distribution — fast but underestimates tail risk.
    """
    arr = np.asarray(returns, dtype=float)
    arr = arr[np.isfinite(arr)]

    if len(arr) < 20:
        return {"var": 0.0, "cvar": 0.0, "mu": 0.0, "sigma": 0.0}

    mu = float(np.mean(arr))
    sigma = float(np.std(arr, ddof=1))

    z = Z_SCORES.get(confidence, 1.645)
    var = mu - z * sigma * np.sqrt(horizon_days)

    # CVaR for normal distribution: μ − σ × φ(z) / α
    alpha = 1.0 - confidence
    phi_z = float(np.exp(-0.5 * z**2) / np.sqrt(2 * np.pi))
    cvar = mu - sigma * phi_z / alpha

    return {
        "var": round(var, 6),
        "cvar": round(cvar, 6),
        "mu": round(mu, 6),
        "sigma": round(sigma, 6),
    }


def compute_monte_carlo_var(
    returns: pd.Series | np.ndarray,
    confidence: float = 0.95,
    n_simulations: int = MC_SIMULATIONS,
    horizon_days: int = MC_HORIZON_DAYS,
) -> dict[str, float]:
    """Monte Carlo VaR: bootstrap N portfolio paths from historical returns.

    Non-parametric: preserves fat tails and autocorrelation structure.
    """
    arr = np.asarray(returns, dtype=float)
    arr = arr[np.isfinite(arr)]

    if len(arr) < 30:
        return {"var": 0.0, "cvar": 0.0, "n_simulations": 0}

    rng = np.random.default_rng()

    sim_indices = rng.integers(0, len(arr), size=(n_simulations, horizon_days))
    sim_returns = arr[sim_indices]

    if horizon_days > 1:
        cumulative_returns = np.prod(1 + sim_returns, axis=1) - 1
    else:
        cumulative_returns = sim_returns.ravel()

    alpha = 1.0 - confidence
    var = float(np.percentile(cumulative_returns, alpha * 100))

    tail = cumulative_returns[cumulative_returns <= var]
    cvar = float(tail.mean()) if len(tail) > 0 else var

    return {
        "var": round(var, 6),
        "cvar": round(cvar, 6),
        "n_simulations": n_simulations,
    }


def compute_portfolio_var(
    position_returns: dict[str, pd.Series],
    weights: dict[str, float],
    confidence: float = 0.95,
    vol: VolContext | None = None,
) -> dict:
    """Portfolio-level VaR using weighted return series.

    Combines individual position returns into a portfolio return series
    and computes VaR using all three methods.

    Args:
        position_returns: {ticker: daily_return_series}
        weights: {ticker: portfolio_weight} (fractions, sum ≤ 1.0)
        confidence: VaR confidence level
        vol: optional VolContext for regime-aware adjustments
    """
    if not position_returns or not weights:
        return _empty_portfolio_var()

    tickers = [t for t in weights if t in position_returns]
    if not tickers:
        return _empty_portfolio_var()

    min_len = min(len(position_returns[t]) for t in tickers)
    if min_len < 20:
        return _empty_portfolio_var()

    aligned = pd.DataFrame(
        {t: position_returns[t].iloc[-min_len:].values for t in tickers}
    )
    aligned = aligned.dropna()

    if aligned.empty:
        return _empty_portfolio_var()

    w = np.array([weights[t] for t in tickers])
    portfolio_returns = aligned.values @ w

    hist = compute_historical_var(portfolio_returns, confidence)
    param = compute_parametric_var(portfolio_returns, confidence)
    mc = compute_monte_carlo_var(portfolio_returns, confidence)

    # Use historical as primary (most conservative for fat tails)
    primary_var = hist["var"]

    vol_adjustment = 1.0
    if vol is not None and vol.vol_scale > 1.5:
        vol_adjustment = min(2.0, vol.vol_scale)
        primary_var *= vol_adjustment

    return {
        "portfolio_var_95": round(primary_var, 6),
        "portfolio_cvar_95": round(hist["cvar"] * vol_adjustment, 6),
        "historical": hist,
        "parametric": param,
        "monte_carlo": mc,
        "vol_adjustment": round(vol_adjustment, 3),
        "n_positions": len(tickers),
        "observation_days": len(aligned),
        "breaches_2pct_limit": abs(primary_var) > 0.02,
    }


def compute_incremental_var(
    existing_returns: pd.Series | np.ndarray,
    new_position_returns: pd.Series | np.ndarray,
    new_weight: float,
    confidence: float = 0.95,
) -> dict[str, float]:
    """Marginal VaR impact of adding a new position.

    Compares portfolio VaR before and after adding the new position.
    Used by the portfolio constructor to reject positions that push
    VaR beyond the 2% daily limit.
    """
    existing = np.asarray(existing_returns, dtype=float)
    new_pos = np.asarray(new_position_returns, dtype=float)

    min_len = min(len(existing), len(new_pos))
    if min_len < 20:
        return {"incremental_var": 0.0, "var_before": 0.0, "var_after": 0.0}

    existing = existing[-min_len:]
    new_pos = new_pos[-min_len:]

    var_before = compute_historical_var(existing, confidence)["var"]

    combined = existing * (1 - new_weight) + new_pos * new_weight
    var_after = compute_historical_var(combined, confidence)["var"]

    return {
        "incremental_var": round(var_after - var_before, 6),
        "var_before": round(var_before, 6),
        "var_after": round(var_after, 6),
        "exceeds_limit": abs(var_after) > 0.02,
    }


def _empty_portfolio_var() -> dict:
    return {
        "portfolio_var_95": 0.0,
        "portfolio_cvar_95": 0.0,
        "historical": {"var": 0.0, "cvar": 0.0, "n_observations": 0},
        "parametric": {"var": 0.0, "cvar": 0.0, "mu": 0.0, "sigma": 0.0},
        "monte_carlo": {"var": 0.0, "cvar": 0.0, "n_simulations": 0},
        "vol_adjustment": 1.0,
        "n_positions": 0,
        "observation_days": 0,
        "breaches_2pct_limit": False,
    }

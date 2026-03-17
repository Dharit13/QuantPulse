"""Statistical validation for backtest results.

Implements the spec's "REQUIRED MINIMUM STATS FOR A LIVE SIGNAL" gate
plus proper multiple-hypothesis correction so we don't fool ourselves
with data-mined results.

Tests:
  - Bonferroni / Holm-Bonferroni p-value correction
  - Bootstrap confidence interval for Sharpe ratio
  - Permutation test (strategy vs random)
  - Rolling 6-month window positivity check
  - Threshold gate (Sharpe, win rate, profit factor, drawdown, trade count)
"""

from __future__ import annotations

import numpy as np


# ── Spec thresholds (Section 15) ──

MIN_SHARPE = 1.5
MIN_WIN_RATE = 0.50
MIN_WIN_RATE_ALT = 0.40
MIN_WIN_LOSS_RATIO_ALT = 2.0
MIN_PROFIT_FACTOR = 1.5
MAX_DRAWDOWN = -0.15
MIN_TRADES = 100
MAX_PVALUE = 0.01
MIN_POSITIVE_WINDOWS = 0.60

ROLLING_WINDOW_DAYS = 126  # ~6 months of trading days


def bonferroni_correction(p_values: list[float]) -> list[float]:
    """Multiply each p-value by the number of hypotheses tested."""
    n = len(p_values)
    return [min(1.0, p * n) for p in p_values]


def holm_bonferroni_correction(p_values: list[float]) -> list[float]:
    """Step-down procedure — less conservative than Bonferroni."""
    n = len(p_values)
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    adjusted = [0.0] * n

    cumulative_max = 0.0
    for rank, (orig_idx, p) in enumerate(indexed):
        adj = p * (n - rank)
        cumulative_max = max(cumulative_max, adj)
        adjusted[orig_idx] = min(1.0, cumulative_max)

    return adjusted


def bootstrap_sharpe_ci(
    trade_returns: list[float],
    n_bootstrap: int = 10_000,
    confidence: float = 0.95,
    risk_free_daily: float = 0.0002,
) -> dict:
    """Bootstrap confidence interval for the annualised Sharpe ratio."""
    if len(trade_returns) < 10:
        return {"lower": 0.0, "upper": 0.0, "median": 0.0, "n_samples": 0}

    arr = np.array(trade_returns)
    rng = np.random.default_rng(42)
    sharpes = np.empty(n_bootstrap)

    for i in range(n_bootstrap):
        sample = rng.choice(arr, size=len(arr), replace=True)
        excess = sample - risk_free_daily
        std = np.std(excess)
        sharpes[i] = float(np.mean(excess) / std * np.sqrt(252)) if std > 0 else 0.0

    alpha = (1 - confidence) / 2
    lower = float(np.percentile(sharpes, alpha * 100))
    upper = float(np.percentile(sharpes, (1 - alpha) * 100))
    median = float(np.median(sharpes))

    return {
        "lower": round(lower, 3),
        "upper": round(upper, 3),
        "median": round(median, 3),
        "n_samples": n_bootstrap,
    }


def permutation_test(
    trade_returns: list[float],
    n_permutations: int = 10_000,
) -> dict:
    """Test whether strategy mean return is significantly different from zero.

    Shuffles the signs of returns (equivalent to randomly assigning
    long/short) and checks how often the shuffled mean exceeds the
    observed mean.
    """
    if len(trade_returns) < 10:
        return {"p_value": 1.0, "observed_mean": 0.0, "n_permutations": 0}

    arr = np.array(trade_returns)
    observed = float(np.mean(arr))
    rng = np.random.default_rng(42)

    count_ge = 0
    for _ in range(n_permutations):
        signs = rng.choice([-1, 1], size=len(arr))
        shuffled_mean = float(np.mean(arr * signs))
        if shuffled_mean >= observed:
            count_ge += 1

    p_value = count_ge / n_permutations

    return {
        "p_value": round(p_value, 6),
        "observed_mean": round(observed, 6),
        "n_permutations": n_permutations,
    }


def rolling_window_check(
    trade_returns: list[float],
    window_size: int = ROLLING_WINDOW_DAYS,
) -> dict:
    """Check that returns are positive in ≥60% of rolling 6-month windows."""
    if len(trade_returns) < window_size:
        return {"pct_positive_windows": 0.0, "n_windows": 0, "passed": False}

    arr = np.array(trade_returns)
    n_windows = len(arr) - window_size + 1
    positive = 0

    cumsum = np.cumsum(np.insert(arr, 0, 0))
    for i in range(n_windows):
        window_sum = cumsum[i + window_size] - cumsum[i]
        if window_sum > 0:
            positive += 1

    pct = positive / n_windows if n_windows > 0 else 0.0

    return {
        "pct_positive_windows": round(pct, 4),
        "n_windows": n_windows,
        "passed": pct >= MIN_POSITIVE_WINDOWS,
    }


def run_validation(
    trade_returns: list[float],
    n_variants: int = 1,
    sharpe: float | None = None,
    win_rate: float | None = None,
    profit_factor: float | None = None,
    max_drawdown: float | None = None,
) -> dict:
    """Run the full validation suite and return a structured report.

    This is the function imported by walk_forward.py to populate the
    ``validation`` field of BacktestResult.
    """
    arr = np.array(trade_returns) if trade_returns else np.array([])
    n_trades = len(arr)

    # Compute stats from returns if not provided
    if sharpe is None and n_trades > 1:
        std = float(np.std(arr))
        sharpe = float(np.mean(arr) / std * np.sqrt(252)) if std > 0 else 0.0
    sharpe = sharpe or 0.0

    if win_rate is None and n_trades > 0:
        win_rate = float(np.sum(arr > 0) / n_trades)
    win_rate = win_rate or 0.0

    wins = arr[arr > 0]
    losses = arr[arr <= 0]
    avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.0
    avg_loss = float(np.mean(np.abs(losses))) if len(losses) > 0 else 0.0
    win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else float("inf")

    if profit_factor is None:
        gross_p = float(np.sum(wins)) if len(wins) > 0 else 0.0
        gross_l = float(np.sum(np.abs(losses))) if len(losses) > 0 else 0.0
        profit_factor = gross_p / gross_l if gross_l > 0 else float("inf")
    profit_factor = min(profit_factor, 99.0)

    max_drawdown = max_drawdown or 0.0

    # Individual checks
    checks: dict[str, dict] = {}

    checks["sharpe"] = {
        "value": round(sharpe, 3),
        "threshold": MIN_SHARPE,
        "passed": sharpe >= MIN_SHARPE,
    }

    win_rate_ok = win_rate >= MIN_WIN_RATE or (
        win_rate >= MIN_WIN_RATE_ALT and win_loss_ratio >= MIN_WIN_LOSS_RATIO_ALT
    )
    checks["win_rate"] = {
        "value": round(win_rate, 4),
        "threshold": MIN_WIN_RATE,
        "alt_threshold": f"{MIN_WIN_RATE_ALT} with W/L >= {MIN_WIN_LOSS_RATIO_ALT}",
        "win_loss_ratio": round(win_loss_ratio, 3),
        "passed": win_rate_ok,
    }

    checks["profit_factor"] = {
        "value": round(profit_factor, 3),
        "threshold": MIN_PROFIT_FACTOR,
        "passed": profit_factor >= MIN_PROFIT_FACTOR,
    }

    checks["max_drawdown"] = {
        "value": round(max_drawdown, 4),
        "threshold": MAX_DRAWDOWN,
        "passed": max_drawdown >= MAX_DRAWDOWN,
    }

    checks["trade_count"] = {
        "value": n_trades,
        "threshold": MIN_TRADES,
        "passed": n_trades >= MIN_TRADES,
    }

    # Statistical tests
    perm = permutation_test(trade_returns)
    raw_p = perm["p_value"]
    if n_variants > 1:
        adjusted = bonferroni_correction([raw_p] * n_variants)
        adj_p = adjusted[0]
    else:
        adj_p = raw_p

    checks["p_value"] = {
        "raw": raw_p,
        "adjusted": round(adj_p, 6),
        "n_variants": n_variants,
        "threshold": MAX_PVALUE,
        "passed": adj_p < MAX_PVALUE,
    }

    bootstrap = bootstrap_sharpe_ci(trade_returns)
    checks["bootstrap_sharpe"] = bootstrap

    rolling = rolling_window_check(trade_returns)
    checks["rolling_windows"] = rolling

    all_passed = all(
        c.get("passed", True)
        for c in checks.values()
        if isinstance(c, dict) and "passed" in c
    )

    return {
        "passed": all_passed,
        "checks": checks,
    }

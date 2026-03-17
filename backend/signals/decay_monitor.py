"""Alpha Decay & Signal Freshness monitoring.

Every signal decays over time as more market participants discover it.
This module tracks rolling Sharpe ratios and detects crowding, triggering
allocation adjustments before alpha disappears entirely.

Alert thresholds (spec §13):
  - 30-day Sharpe < 0.5  →  WARNING: signal may be decaying
  - 90-day Sharpe < 0.3  →  CRITICAL: reduce allocation by 50%
  - 252-day Sharpe < 0    →  KILL: disable the signal

Crowding detection:
  - Correlation with factor ETFs (MTUM, VLUE, QUAL) > 0.6 = crowded
  - Rising borrow costs on short positions = crowded short

Reference: QUANTPULSE_FINAL_SPEC.md §13
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
import pandas as pd

from backend.data.fetcher import data_fetcher

logger = logging.getLogger(__name__)

RISK_FREE_RATE = 0.05
FACTOR_ETFS = {
    "momentum": "MTUM",
    "value": "VLUE",
    "quality": "QUAL",
    "low_vol": "USMV",
    "size": "IWM",
}
CROWDING_THRESHOLD = 0.60
ROLLING_WINDOWS = (30, 90, 252)


class DecayStatus(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    KILL = "kill"


@dataclass
class DecayReport:
    """Alpha decay assessment for a single strategy or signal."""

    strategy: str
    status: DecayStatus
    sharpe_30d: float = 0.0
    sharpe_90d: float = 0.0
    sharpe_252d: float = 0.0
    allocation_multiplier: float = 1.0
    crowding_score: float = 0.0
    crowded_factors: list[str] = field(default_factory=list)
    recommendation: str = ""


def compute_rolling_sharpe(
    returns: pd.Series | np.ndarray,
    window: int = 30,
    annualize: bool = True,
) -> float:
    """Compute Sharpe ratio over a rolling window.

    Sharpe = (R_p − R_f) / σ_p × √252  (annualized from daily)
    """
    arr = np.asarray(returns, dtype=float)
    arr = arr[np.isfinite(arr)]

    if len(arr) < max(10, window // 2):
        return 0.0

    arr = arr[-window:]

    mu = float(np.mean(arr))
    sigma = float(np.std(arr, ddof=1))

    if sigma < 1e-10:
        return 0.0

    daily_rf = RISK_FREE_RATE / 252
    excess = mu - daily_rf

    if annualize:
        return float(excess / sigma * np.sqrt(252))
    return float(excess / sigma)


def assess_signal_decay(
    strategy: str,
    returns: pd.Series | np.ndarray,
) -> DecayReport:
    """Full decay assessment for a strategy's return stream.

    Computes rolling Sharpe at 30/90/252-day windows and classifies status.
    """
    arr = np.asarray(returns, dtype=float)
    arr = arr[np.isfinite(arr)]

    sharpe_30d = compute_rolling_sharpe(arr, window=30)
    sharpe_90d = compute_rolling_sharpe(arr, window=90)
    sharpe_252d = compute_rolling_sharpe(arr, window=252)

    status, multiplier, rec = _classify_decay(sharpe_30d, sharpe_90d, sharpe_252d)

    return DecayReport(
        strategy=strategy,
        status=status,
        sharpe_30d=round(sharpe_30d, 3),
        sharpe_90d=round(sharpe_90d, 3),
        sharpe_252d=round(sharpe_252d, 3),
        allocation_multiplier=multiplier,
        recommendation=rec,
    )


def detect_crowding(
    strategy_returns: pd.Series | np.ndarray,
    lookback_days: int = 90,
) -> dict:
    """Detect if strategy returns are correlated with popular factor ETFs.

    High correlation with MTUM/VLUE/QUAL = our signals are crowded.
    Crowded signals face adverse selection and capacity constraints.
    """
    strat = np.asarray(strategy_returns, dtype=float)
    strat = strat[np.isfinite(strat)]

    if len(strat) < 30:
        return {
            "is_crowded": False,
            "crowding_score": 0.0,
            "factor_correlations": {},
            "crowded_factors": [],
        }

    strat = strat[-lookback_days:]

    factor_corrs: dict[str, float] = {}
    crowded: list[str] = []

    for factor_name, etf_ticker in FACTOR_ETFS.items():
        try:
            df = data_fetcher.get_daily_ohlcv(etf_ticker, period="6mo")
            if df.empty or len(df) < 30:
                continue

            etf_returns = df["Close"].pct_change().dropna().values
            etf_returns = etf_returns[-lookback_days:]

            min_len = min(len(strat), len(etf_returns))
            if min_len < 20:
                continue

            corr = float(np.corrcoef(
                strat[-min_len:], etf_returns[-min_len:]
            )[0, 1])

            if np.isfinite(corr):
                factor_corrs[factor_name] = round(corr, 4)
                if abs(corr) > CROWDING_THRESHOLD:
                    crowded.append(factor_name)
        except Exception:
            logger.debug("Failed to fetch factor ETF %s for crowding check", etf_ticker)

    crowding_score = 0.0
    if factor_corrs:
        crowding_score = float(np.mean([abs(c) for c in factor_corrs.values()]))

    return {
        "is_crowded": len(crowded) > 0,
        "crowding_score": round(crowding_score, 4),
        "factor_correlations": factor_corrs,
        "crowded_factors": crowded,
    }


def full_decay_report(
    strategy: str,
    returns: pd.Series | np.ndarray,
) -> DecayReport:
    """Combined decay + crowding assessment."""
    report = assess_signal_decay(strategy, returns)

    crowding = detect_crowding(returns)
    report.crowding_score = crowding["crowding_score"]
    report.crowded_factors = crowding["crowded_factors"]

    if crowding["is_crowded"]:
        report.allocation_multiplier = min(
            report.allocation_multiplier,
            max(0.3, 1.0 - crowding["crowding_score"]),
        )
        if report.status == DecayStatus.HEALTHY:
            report.status = DecayStatus.WARNING
        report.recommendation += (
            f" Crowded with factors: {', '.join(crowding['crowded_factors'])}."
            f" Reduce sizing by {(1 - report.allocation_multiplier):.0%}."
        )

    return report


def scan_all_strategies(
    strategy_returns: dict[str, pd.Series | np.ndarray],
) -> dict[str, DecayReport]:
    """Run decay + crowding analysis across all active strategies.

    Args:
        strategy_returns: {strategy_name: daily_return_series}

    Returns:
        {strategy_name: DecayReport}
    """
    results: dict[str, DecayReport] = {}

    for strategy, returns in strategy_returns.items():
        try:
            results[strategy] = full_decay_report(strategy, returns)
        except Exception:
            logger.exception("Decay scan failed for strategy %s", strategy)
            results[strategy] = DecayReport(
                strategy=strategy,
                status=DecayStatus.WARNING,
                recommendation="Decay scan failed — defaulting to WARNING",
            )

    killed = [s for s, r in results.items() if r.status == DecayStatus.KILL]
    critical = [s for s, r in results.items() if r.status == DecayStatus.CRITICAL]

    if killed:
        logger.warning("KILL signals detected for strategies: %s", killed)
    if critical:
        logger.warning("CRITICAL decay for strategies: %s", critical)

    return results


def compute_signal_half_life(
    returns: pd.Series | np.ndarray,
    initial_window: int = 30,
    step: int = 5,
) -> dict:
    """Estimate how quickly a signal's edge decays after entry.

    Computes cumulative return at expanding windows to find the point
    where expected return starts declining (the "half-life" of the edge).
    """
    arr = np.asarray(returns, dtype=float)
    arr = arr[np.isfinite(arr)]

    if len(arr) < initial_window + step * 3:
        return {"half_life_days": None, "peak_return_day": None, "curve": []}

    curve: list[dict] = []
    peak_return = -np.inf
    peak_day = 0

    for end in range(initial_window, len(arr), step):
        window_returns = arr[:end]
        cum_return = float(np.prod(1 + window_returns) - 1)
        daily_sharpe = compute_rolling_sharpe(window_returns, window=len(window_returns))

        curve.append({
            "days": end,
            "cumulative_return": round(cum_return, 6),
            "sharpe": round(daily_sharpe, 3),
        })

        if cum_return > peak_return:
            peak_return = cum_return
            peak_day = end

    half_life = None
    if peak_day < len(arr) - step:
        half_target = peak_return / 2
        for point in curve:
            if point["days"] > peak_day and point["cumulative_return"] <= half_target:
                half_life = point["days"] - peak_day
                break

    return {
        "half_life_days": half_life,
        "peak_return_day": peak_day,
        "peak_return": round(peak_return, 6),
        "curve": curve,
    }


# ── Internal helpers ──────────────────────────────────────────────────


def _classify_decay(
    sharpe_30d: float,
    sharpe_90d: float,
    sharpe_252d: float,
) -> tuple[DecayStatus, float, str]:
    """Classify decay status from rolling Sharpe values.

    Returns (status, allocation_multiplier, recommendation).
    """
    if sharpe_252d < 0 and sharpe_90d < 0:
        return (
            DecayStatus.KILL,
            0.0,
            "252-day and 90-day Sharpe both negative. "
            "Disable signal and investigate root cause.",
        )

    if sharpe_90d < 0.3:
        return (
            DecayStatus.CRITICAL,
            0.5,
            f"90-day Sharpe={sharpe_90d:.2f} below 0.3 threshold. "
            f"Reduce allocation by 50%. Consider disabling if trend continues.",
        )

    if sharpe_30d < 0.5:
        return (
            DecayStatus.WARNING,
            0.75,
            f"30-day Sharpe={sharpe_30d:.2f} below 0.5. "
            f"Signal may be decaying. Monitor closely, reduce by 25%.",
        )

    return (
        DecayStatus.HEALTHY,
        1.0,
        f"All rolling Sharpe windows healthy "
        f"(30d={sharpe_30d:.2f}, 90d={sharpe_90d:.2f}, 252d={sharpe_252d:.2f}).",
    )

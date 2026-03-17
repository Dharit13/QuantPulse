"""Portfolio correlation monitoring.

Enforces the risk limit: no two positions with > 0.8 trailing 60-day
correlation (spec §11 Layer 3).  Provides utilities for:

  - Pairwise correlation matrix for current positions
  - Detection of correlation clusters (groups of tightly-correlated names)
  - Redundancy scoring: if adding a new position is too correlated with
    existing holdings, flag it for size reduction or rejection
  - Average portfolio correlation for VolContext enrichment

Also feeds into the portfolio constructor (correlation-aware dedup)
and the risk manager (correlation-based position scaling).

Reference: QUANTPULSE_FINAL_SPEC.md §11, §12
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from backend.adaptive.vol_context import VolContext
from backend.data.fetcher import data_fetcher

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 60
MIN_OBSERVATIONS = 20
HIGH_CORRELATION_THRESHOLD = 0.70
REJECTION_THRESHOLD = 0.80


def compute_correlation_matrix(
    tickers: list[str],
    lookback_days: int = LOOKBACK_DAYS,
) -> pd.DataFrame:
    """Compute pairwise correlation matrix for a set of tickers.

    Uses trailing daily returns over lookback_days.
    Returns an N×N DataFrame (tickers as both index and columns).
    """
    if len(tickers) < 2:
        return pd.DataFrame(1.0, index=tickers, columns=tickers)

    returns_dict: dict[str, pd.Series] = {}
    for ticker in tickers:
        df = data_fetcher.get_daily_ohlcv(ticker, period="6mo")
        if df.empty or len(df) < MIN_OBSERVATIONS:
            continue
        rets = df["Close"].pct_change().dropna().tail(lookback_days)
        if len(rets) >= MIN_OBSERVATIONS:
            returns_dict[ticker] = rets

    if len(returns_dict) < 2:
        return pd.DataFrame(1.0, index=tickers, columns=tickers)

    returns_df = pd.DataFrame(returns_dict)
    returns_df = returns_df.dropna()

    if len(returns_df) < MIN_OBSERVATIONS:
        return pd.DataFrame(
            np.eye(len(returns_dict)),
            index=list(returns_dict.keys()),
            columns=list(returns_dict.keys()),
        )

    return returns_df.corr()


def compute_position_returns(
    tickers: list[str],
    lookback_days: int = LOOKBACK_DAYS,
) -> dict[str, pd.Series]:
    """Fetch daily return series for a set of tickers.

    Utility used by both VaR and correlation modules.
    """
    result: dict[str, pd.Series] = {}
    for ticker in tickers:
        df = data_fetcher.get_daily_ohlcv(ticker, period="6mo")
        if df.empty or len(df) < MIN_OBSERVATIONS:
            continue
        rets = df["Close"].pct_change().dropna().tail(lookback_days)
        if len(rets) >= MIN_OBSERVATIONS:
            result[ticker] = rets
    return result


def check_new_position_correlation(
    new_ticker: str,
    existing_tickers: list[str],
    lookback_days: int = LOOKBACK_DAYS,
) -> dict:
    """Check if a proposed new position is too correlated with existing holdings.

    Returns:
        {
            "approved": bool,
            "max_correlation": float,
            "most_correlated_with": str | None,
            "avg_correlation": float,
            "pairwise": dict[str, float],
            "size_haircut": float,  (1.0 = no reduction, 0.5 = halve the position)
        }
    """
    if not existing_tickers:
        return {
            "approved": True,
            "max_correlation": 0.0,
            "most_correlated_with": None,
            "avg_correlation": 0.0,
            "pairwise": {},
            "size_haircut": 1.0,
        }

    all_tickers = [new_ticker] + existing_tickers
    corr_matrix = compute_correlation_matrix(all_tickers, lookback_days)

    if new_ticker not in corr_matrix.index:
        return {
            "approved": True,
            "max_correlation": 0.0,
            "most_correlated_with": None,
            "avg_correlation": 0.0,
            "pairwise": {},
            "size_haircut": 1.0,
        }

    new_row = corr_matrix.loc[new_ticker]
    pairwise = {
        t: round(float(new_row[t]), 4)
        for t in existing_tickers
        if t in new_row.index and t != new_ticker
    }

    if not pairwise:
        return {
            "approved": True,
            "max_correlation": 0.0,
            "most_correlated_with": None,
            "avg_correlation": 0.0,
            "pairwise": {},
            "size_haircut": 1.0,
        }

    max_corr = max(pairwise.values())
    most_corr_with = max(pairwise, key=pairwise.get)
    avg_corr = float(np.mean(list(pairwise.values())))

    if max_corr > REJECTION_THRESHOLD:
        approved = False
        size_haircut = 0.0
    elif max_corr > HIGH_CORRELATION_THRESHOLD:
        approved = True
        size_haircut = max(0.3, 1.0 - (max_corr - HIGH_CORRELATION_THRESHOLD) * 3.0)
    else:
        approved = True
        size_haircut = 1.0

    return {
        "approved": approved,
        "max_correlation": round(max_corr, 4),
        "most_correlated_with": most_corr_with,
        "avg_correlation": round(avg_corr, 4),
        "pairwise": pairwise,
        "size_haircut": round(size_haircut, 3),
    }


def detect_correlation_clusters(
    tickers: list[str],
    threshold: float = HIGH_CORRELATION_THRESHOLD,
    lookback_days: int = LOOKBACK_DAYS,
) -> list[list[str]]:
    """Find groups of tickers with intra-group correlation above threshold.

    Uses a simple greedy clustering: start from the highest-correlation pair
    and build clusters by adding tickers whose avg correlation to the cluster
    exceeds the threshold.
    """
    if len(tickers) < 2:
        return []

    corr_matrix = compute_correlation_matrix(tickers, lookback_days)
    available = set(corr_matrix.index)
    clusters: list[list[str]] = []

    while len(available) >= 2:
        best_pair = None
        best_corr = -1.0

        avail_list = sorted(available)
        for i, t1 in enumerate(avail_list):
            for t2 in avail_list[i + 1:]:
                if t1 in corr_matrix.index and t2 in corr_matrix.columns:
                    c = abs(float(corr_matrix.loc[t1, t2]))
                    if c > best_corr:
                        best_corr = c
                        best_pair = (t1, t2)

        if best_pair is None or best_corr < threshold:
            break

        cluster = list(best_pair)
        available -= set(best_pair)

        for t in sorted(available):
            if t not in corr_matrix.index:
                continue
            avg_corr_to_cluster = float(np.mean([
                abs(float(corr_matrix.loc[t, ct]))
                for ct in cluster
                if ct in corr_matrix.columns
            ]))
            if avg_corr_to_cluster >= threshold:
                cluster.append(t)
                available.discard(t)

        if len(cluster) >= 2:
            clusters.append(cluster)

    return clusters


def compute_average_portfolio_correlation(
    tickers: list[str],
    lookback_days: int = LOOKBACK_DAYS,
) -> float:
    """Average pairwise correlation across all positions.

    Used to populate VolContext.avg_sp500_correlation_20d and for
    portfolio-level risk assessment.
    """
    if len(tickers) < 2:
        return 0.0

    corr_matrix = compute_correlation_matrix(tickers, lookback_days)

    n = len(corr_matrix)
    if n < 2:
        return 0.0

    mask = np.triu(np.ones((n, n), dtype=bool), k=1)
    upper_values = corr_matrix.values[mask]
    upper_values = upper_values[np.isfinite(upper_values)]

    return float(np.mean(upper_values)) if len(upper_values) > 0 else 0.0


def get_portfolio_correlation_report(
    tickers: list[str],
    vol: VolContext | None = None,
    lookback_days: int = LOOKBACK_DAYS,
) -> dict:
    """Full correlation report for the current portfolio.

    Returns avg correlation, clusters, flagged pairs, and risk assessment.
    """
    avg_corr = compute_average_portfolio_correlation(tickers, lookback_days)
    clusters = detect_correlation_clusters(tickers, HIGH_CORRELATION_THRESHOLD, lookback_days)
    corr_matrix = compute_correlation_matrix(tickers, lookback_days)

    # Find pairs exceeding the hard limit
    flagged_pairs: list[dict] = []
    for i, t1 in enumerate(tickers):
        for t2 in tickers[i + 1:]:
            if t1 in corr_matrix.index and t2 in corr_matrix.columns:
                c = float(corr_matrix.loc[t1, t2])
                if abs(c) > REJECTION_THRESHOLD:
                    flagged_pairs.append({
                        "ticker_a": t1,
                        "ticker_b": t2,
                        "correlation": round(c, 4),
                        "action": "reduce_one",
                    })

    # Classification
    if avg_corr > 0.6:
        regime = "herding"
    elif avg_corr > 0.3:
        regime = "normal"
    else:
        regime = "dispersed"

    return {
        "avg_correlation": round(avg_corr, 4),
        "correlation_regime": regime,
        "n_positions": len(tickers),
        "n_clusters": len(clusters),
        "clusters": clusters,
        "flagged_pairs": flagged_pairs,
        "risk_level": (
            "high" if avg_corr > 0.6
            else "moderate" if avg_corr > 0.4
            else "low"
        ),
    }

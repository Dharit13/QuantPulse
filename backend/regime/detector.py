"""Regime Detection Engine.

Classifies the current market into one of 5 regimes using 4 indicator pillars.
Outputs both a primary regime and a probability distribution for smooth blending.
"""

import logging

import pandas as pd

from backend.adaptive.vol_context import VolContext
from backend.adaptive.weight_interpolation import STRATEGY_WEIGHTS, compute_blended_weights
from backend.models.schemas import Regime
from backend.regime.indicators import (
    compute_adx_indicator,
    compute_breadth_indicator,
    compute_cross_asset_confirmation,
    compute_vix_indicator,
)

logger = logging.getLogger(__name__)

REGIMES = list(Regime)


def detect_regime(
    vix_df: pd.DataFrame,
    spy_df: pd.DataFrame,
    pct_above_200sma: float | None = None,
    yield_curve_slope: float | None = None,
    credit_spread_ratio: float | None = None,
) -> dict:
    """Detect current market regime and output probability distribution.

    Returns:
        {
            "regime": Regime,
            "confidence": float,
            "probabilities": {regime_name: probability},
            "indicators": {indicator details},
            "strategy_weights": {strategy: weight},
        }
    """
    vix_result = compute_vix_indicator(vix_df)
    breadth_result = compute_breadth_indicator(pct_above_200sma=pct_above_200sma)
    adx_result = compute_adx_indicator(spy_df)
    cross_result = compute_cross_asset_confirmation(yield_curve_slope, credit_spread_ratio)

    # Score each regime based on indicator votes
    regime_scores = {r.value: 0.0 for r in Regime}

    # VIX indicator (25% weight)
    vix = vix_result["vix"]
    ts = vix_result["term_structure"]
    if vix < 15 and ts == "contango":
        regime_scores["bull_trend"] += 0.25
    elif vix < 25 and ts in ("contango", "flat"):
        regime_scores["bull_choppy"] += 0.25
    elif 25 <= vix < 35 and ts == "backwardation":
        regime_scores["bear_trend"] += 0.25
    elif vix >= 35:
        regime_scores["crisis"] += 0.25
    else:
        regime_scores["bull_choppy"] += 0.15
        regime_scores["mean_reverting"] += 0.10

    # Breadth indicator (25% weight)
    breadth_signal = breadth_result["signal"]
    if breadth_signal == "bull_trend":
        regime_scores["bull_trend"] += 0.25
    elif breadth_signal == "bull_choppy":
        regime_scores["bull_choppy"] += 0.25
    elif breadth_signal == "bear_or_mean_revert":
        regime_scores["bear_trend"] += 0.15
        regime_scores["mean_reverting"] += 0.10
    elif breadth_signal == "crisis":
        regime_scores["crisis"] += 0.25

    # ADX indicator (25% weight)
    adx_signal = adx_result["signal"]
    if adx_signal == "bull_trend":
        regime_scores["bull_trend"] += 0.25
    elif adx_signal == "bear_trend":
        regime_scores["bear_trend"] += 0.25
    elif adx_signal == "mean_reverting":
        regime_scores["mean_reverting"] += 0.25
    elif adx_signal == "choppy":
        regime_scores["bull_choppy"] += 0.15
        regime_scores["mean_reverting"] += 0.10

    # Cross-asset (25% weight)
    cross_signal = cross_result["signal"]
    if cross_signal == "risk_on":
        regime_scores["bull_trend"] += 0.15
        regime_scores["bull_choppy"] += 0.10
    elif cross_signal == "risk_off":
        regime_scores["bear_trend"] += 0.15
        regime_scores["crisis"] += 0.10
    else:
        regime_scores["bull_choppy"] += 0.10
        regime_scores["mean_reverting"] += 0.15

    # Normalize to probabilities
    total = sum(regime_scores.values())
    if total > 0:
        probabilities = {k: round(v / total, 4) for k, v in regime_scores.items()}
    else:
        probabilities = {r.value: 0.2 for r in Regime}

    # Primary regime = highest probability
    primary = max(probabilities, key=probabilities.get)
    confidence = probabilities[primary]

    # Compute blended strategy weights
    weights = compute_blended_weights(probabilities)

    return {
        "regime": Regime(primary),
        "confidence": confidence,
        "probabilities": probabilities,
        "indicators": {
            "vix": vix_result,
            "breadth": breadth_result,
            "adx": adx_result,
            "cross_asset": cross_result,
        },
        "strategy_weights": weights,
    }

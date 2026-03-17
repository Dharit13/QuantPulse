"""Self-calibrating regime thresholds using percentile-based lookback.

Instead of: VIX > 25 -> elevated (absolute)
We use:     VIX > 75th percentile of trailing 252 days (relative)

Recalibrate weekly (Sunday night).
"""

import numpy as np


def calibrate_regime_thresholds(
    vix_history_252d: list[float],
    breadth_history_252d: list[float],
    adx_history_252d: list[float] | None = None,
) -> dict:
    """Compute regime thresholds from trailing 1-year distributions."""
    vix_arr = np.array(vix_history_252d)
    breadth_arr = np.array(breadth_history_252d)

    result = {
        "vix_thresholds": {
            "ultra_low": float(np.percentile(vix_arr, 10)),
            "low": float(np.percentile(vix_arr, 25)),
            "normal": float(np.percentile(vix_arr, 50)),
            "elevated": float(np.percentile(vix_arr, 75)),
            "high": float(np.percentile(vix_arr, 90)),
            "extreme": float(np.percentile(vix_arr, 97)),
        },
        "breadth_thresholds": {
            "crisis": float(np.percentile(breadth_arr, 10)),
            "bear": float(np.percentile(breadth_arr, 30)),
            "neutral": float(np.percentile(breadth_arr, 50)),
            "bull": float(np.percentile(breadth_arr, 70)),
            "strong_bull": float(np.percentile(breadth_arr, 90)),
        },
        "lookback_days": 252,
    }

    if adx_history_252d:
        adx_arr = np.array(adx_history_252d)
        result["adx_thresholds"] = {
            "weak_trend": float(np.percentile(adx_arr, 25)),
            "moderate_trend": float(np.percentile(adx_arr, 50)),
            "strong_trend": float(np.percentile(adx_arr, 75)),
        }

    return result

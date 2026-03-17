"""Speed-adjusted hold durations.

In fast markets (high ATR, high vol): everything happens faster.
In slow markets: patience required, don't close trades early.
Formula: adaptive_hold = base_hold_days / speed_scale
"""

from backend.adaptive.vol_context import VolContext

BASE_HOLD_PERIODS = {
    "stat_arb":       {"min": 3,   "max": 20,  "typical": 10},
    "catalyst_pead":  {"min": 5,   "max": 40,  "typical": 25},
    "catalyst_rev":   {"min": 5,   "max": 30,  "typical": 15},
    "cross_asset":    {"min": 3,   "max": 15,  "typical": 8},
    "flow":           {"min": 2,   "max": 10,  "typical": 5},
    "gap_reversion":  {"min": 0.1, "max": 0.5, "typical": 0.25},
}


def get_adaptive_hold(strategy: str, vol: VolContext) -> dict:
    base = BASE_HOLD_PERIODS.get(strategy, {"min": 3, "max": 20, "typical": 10})
    ss = max(0.5, vol.speed_scale)

    return {
        "min_days": max(1, int(base["min"] / ss)),
        "max_days": max(2, int(base["max"] / ss)),
        "typical_days": max(1, int(base["typical"] / ss)),
        "speed_scale_used": round(ss, 2),
    }

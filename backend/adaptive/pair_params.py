"""Per-pair parameter calibration using pair-specific spread statistics.

A tech pair (NVDA/AMD) moves 3x faster than a utility pair (NEE/DUK).
The same z-score and hold period make no sense for both.
"""

import pandas as pd

from backend.adaptive.vol_context import VolContext


def calibrate_pair_params(
    spread_series: pd.Series,
    half_life: float,
    spread_vol: float,
    vol: VolContext,
) -> dict:
    """Compute pair-specific adaptive parameters."""
    # Entry z-score: inversely proportional to half-life
    base_entry_z = 1.5 + (half_life / 30)

    entry_z = base_entry_z * max(0.8, min(2.0, vol.vol_scale))

    max_hold = int(half_life * 2.0 / max(0.5, vol.speed_scale))

    # Position size: inversely proportional to spread vol
    normal_spread_vol = 0.02
    vol_ratio = spread_vol / normal_spread_vol if normal_spread_vol > 0 else 1.0
    size_adjustment = 1.0 / max(0.5, vol_ratio)

    return {
        "entry_z": round(entry_z, 2),
        "exit_z": round(entry_z * 0.25, 2),
        "stop_z": round(entry_z * 1.75, 2),
        "max_hold_days": max(3, min(60, max_hold)),
        "size_adjustment": round(size_adjustment, 3),
    }

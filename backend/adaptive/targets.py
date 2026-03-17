"""Volatility-scaled profit targets with R/R constraint.

Targets scale with volatility AND maintain minimum 2.0 reward/risk ratio.
"""

from backend.adaptive.vol_context import VolContext


def compute_targets(
    entry_price: float,
    stop_info: dict,
    strategy: str,
    vol: VolContext,
    resistance_levels: list[float] | None = None,
    analyst_target: float | None = None,
) -> list[dict]:
    """Compute adaptive price targets."""
    risk_distance = stop_info["stop_distance_dollars"]
    min_target_distance = risk_distance * 2.0

    preferred_rr = 2.5 * max(1.0, min(1.5, vol.vol_scale))
    preferred_target_distance = risk_distance * preferred_rr

    targets = []

    target_1_price = entry_price + preferred_target_distance
    targets.append({
        "price": round(target_1_price, 2),
        "label": f"Risk-based ({preferred_rr:.1f}:1 R/R)",
        "exit_pct": 50,
    })

    if resistance_levels:
        valid = [r for r in resistance_levels if (r - entry_price) > min_target_distance]
        if valid:
            targets.append({
                "price": round(valid[0], 2),
                "label": "Resistance level",
                "exit_pct": 30,
            })

    if analyst_target and (analyst_target - entry_price) > min_target_distance:
        targets.append({
            "price": round(analyst_target, 2),
            "label": "Analyst consensus",
            "exit_pct": 20,
        })

    if len(targets) == 1:
        targets.append({
            "price": None,
            "label": "Trailing stop (2x ATR)",
            "exit_pct": 50,
        })

    return targets

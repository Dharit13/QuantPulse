"""ATR-based adaptive stop-losses. Never fixed percentage.

Every stop-loss in the system is expressed in ATR multiples:
    stop_price = entry_price - (atr_multiple x ATR_14d x direction)
"""

from backend.adaptive.vol_context import VolContext

BASE_ATR_MULTIPLES = {
    "stat_arb": 2.0,
    "catalyst": 2.5,
    "cross_asset": 3.0,
    "flow": 1.5,
    "gap_reversion": 1.0,
}


def compute_stop(
    entry_price: float,
    direction: str,
    atr_14d: float,
    strategy: str,
    vol: VolContext,
) -> dict:
    """Compute adaptive stop-loss using ATR and vol context."""
    base_mult = BASE_ATR_MULTIPLES.get(strategy, 2.0)

    vol_adjusted_mult = base_mult * max(0.7, min(2.0, vol.vol_scale))

    stop_distance = vol_adjusted_mult * atr_14d

    if direction == "long":
        stop_price = entry_price - stop_distance
    else:
        stop_price = entry_price + stop_distance

    risk_pct = stop_distance / entry_price if entry_price > 0 else 0

    return {
        "stop_price": round(stop_price, 2),
        "stop_distance_dollars": round(stop_distance, 2),
        "atr_multiple_used": round(vol_adjusted_mult, 2),
        "risk_pct": round(risk_pct * 100, 2),
        "atr_14d": round(atr_14d, 2),
    }

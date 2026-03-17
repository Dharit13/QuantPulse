"""Kelly Criterion position sizing.

Standard interface wrapping the adaptive Kelly implementation.
Provides convenience functions for quick Kelly fraction computation.
"""

from backend.adaptive.kelly_adaptive import compute_adaptive_kelly
from backend.adaptive.vol_context import VolContext


def compute_kelly_fraction(
    win_rate: float,
    win_loss_ratio: float,
    use_half_kelly: bool = True,
) -> float:
    """Simple Kelly fraction from win rate and win/loss ratio.

    f* = (p * b - q) / b
    Half-Kelly: f*/2
    """
    p = win_rate
    q = 1 - p
    b = win_loss_ratio

    if b <= 0 or (p * b - q) <= 0:
        return 0.0

    full_kelly = (p * b - q) / b

    if use_half_kelly:
        return full_kelly / 2.0
    return full_kelly


def get_position_size(
    strategy: str,
    vol: VolContext,
    regime: str,
    trailing_trades: list[dict],
    capital: float,
    portfolio_correlation: float = 0.0,
) -> dict:
    """Compute position size in dollars using adaptive Kelly."""
    result = compute_adaptive_kelly(
        strategy=strategy,
        vol=vol,
        regime=regime,
        trailing_trades=trailing_trades,
        portfolio_correlation=portfolio_correlation,
    )

    fraction = result["kelly_fraction"]
    position_dollars = capital * fraction

    return {
        **result,
        "position_dollars": round(position_dollars, 2),
        "position_pct": round(fraction * 100, 2),
    }


# Pre-computed defaults for when no trailing trade data exists
DEFAULT_KELLY_PARAMS = {
    "stat_arb":      {"win_rate": 0.65, "win_loss_ratio": 1.2},
    "catalyst":      {"win_rate": 0.58, "win_loss_ratio": 1.8},
    "cross_asset":   {"win_rate": 0.52, "win_loss_ratio": 2.0},
    "flow":          {"win_rate": 0.55, "win_loss_ratio": 2.0},
    "gap_reversion": {"win_rate": 0.62, "win_loss_ratio": 1.3},
}

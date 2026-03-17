"""Adaptive Kelly Criterion — regime-aware, vol-adjusted position sizing.

Standard Kelly uses fixed p and b. Adaptive Kelly adjusts based on:
1. Trailing performance IN THE CURRENT REGIME
2. Vol-scaled position cap
3. Correlation adjustment
"""

from backend.adaptive.vol_context import VolContext

STRATEGY_CAPS = {
    "stat_arb": 0.06,
    "catalyst": 0.08,
    "cross_asset": 0.05,
    "flow": 0.04,
    "intraday": 0.03,
}

ROLLING_WINDOW = 100


def compute_adaptive_kelly(
    strategy: str,
    vol: VolContext,
    regime: str,
    trailing_trades: list[dict],
    portfolio_correlation: float = 0.0,
) -> dict:
    """Compute regime-aware, vol-adjusted Kelly fraction."""
    # Cap to most recent 100 trades per spec
    trailing_trades = trailing_trades[-ROLLING_WINDOW:]
    regime_trades = [t for t in trailing_trades if t.get("regime") == regime]

    if len(regime_trades) < 20:
        all_wins = [t for t in trailing_trades if t.get("pnl_pct", 0) > 0]
        p = len(all_wins) / max(1, len(trailing_trades)) if trailing_trades else 0.5
        avg_win = (
            sum(t["pnl_pct"] for t in all_wins) / max(1, len(all_wins))
            if all_wins else 0.03
        )
        losses = [t for t in trailing_trades if t.get("pnl_pct", 0) <= 0]
        avg_loss = (
            abs(sum(t["pnl_pct"] for t in losses) / max(1, len(losses)))
            if losses else 0.02
        )
        confidence_penalty = 0.5
    else:
        wins = [t for t in regime_trades if t.get("pnl_pct", 0) > 0]
        p = len(wins) / len(regime_trades)
        avg_win = (
            sum(t["pnl_pct"] for t in wins) / max(1, len(wins))
            if wins else 0.03
        )
        losses = [t for t in regime_trades if t.get("pnl_pct", 0) <= 0]
        avg_loss = (
            abs(sum(t["pnl_pct"] for t in losses) / max(1, len(losses)))
            if losses else 0.02
        )
        confidence_penalty = 1.0

    q = 1 - p
    b = avg_win / max(0.001, avg_loss)

    if (p * b - q) <= 0:
        return {
            "kelly_fraction": 0.0,
            "reason": "Negative expected value in current regime",
            "full_kelly": 0.0,
            "half_kelly": 0.0,
            "win_rate": round(p, 3),
            "win_loss_ratio": round(b, 3),
        }

    full_kelly = (p * b - q) / b
    half_kelly = full_kelly / 2.0
    adjusted_kelly = half_kelly * confidence_penalty
    vol_adjusted = adjusted_kelly * vol.position_scale

    if portfolio_correlation > 0.6:
        corr_haircut = 1.0 - (portfolio_correlation - 0.6) * 1.5
        vol_adjusted *= max(0.4, corr_haircut)

    cap = STRATEGY_CAPS.get(strategy, 0.05)
    final_size = min(vol_adjusted, cap)

    return {
        "kelly_fraction": round(final_size, 4),
        "full_kelly": round(full_kelly, 4),
        "half_kelly": round(half_kelly, 4),
        "win_rate": round(p, 3),
        "win_loss_ratio": round(b, 3),
        "vol_scale_applied": round(vol.position_scale, 3),
        "corr_haircut_applied": round(portfolio_correlation, 3),
        "regime_trades_count": len(regime_trades),
        "confidence_penalty": confidence_penalty,
    }

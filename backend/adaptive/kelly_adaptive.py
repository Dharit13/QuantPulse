"""Adaptive position sizing — regime-aware, vol-adjusted.

Three modes (controlled by config.sizing_mode):
  - "quarter_kelly" (default): f*/4 — conservative until edge validated
  - "half_kelly": f*/2 — use after 6+ months of paper-trade evidence
  - "equal_risk": fixed 1% risk per trade, sized by stop distance

All modes respect per-strategy caps and vol scaling.
"""

from backend.adaptive.vol_context import VolContext
from backend.config import settings

STRATEGY_CAPS = {
    "stat_arb": 0.06,
    "catalyst": 0.08,
    "cross_asset": 0.05,
    "flow": 0.04,
    "intraday": 0.03,
}

ROLLING_WINDOW = 100

KELLY_DIVISORS = {
    "half_kelly": 2.0,
    "quarter_kelly": 4.0,
}


def compute_adaptive_kelly(
    strategy: str,
    vol: VolContext,
    regime: str,
    trailing_trades: list[dict],
    portfolio_correlation: float = 0.0,
    stop_distance_pct: float = 0.0,
) -> dict:
    """Compute position size using the configured sizing mode."""
    sizing_mode = settings.sizing_mode

    # Equal-risk mode bypasses Kelly entirely
    if sizing_mode == "equal_risk":
        return _equal_risk_sizing(strategy, vol, stop_distance_pct)

    # Kelly-based modes (half_kelly, quarter_kelly)
    trailing_trades = trailing_trades[-ROLLING_WINDOW:]
    regime_trades = [t for t in trailing_trades if t.get("regime") == regime]

    if len(regime_trades) < 20:
        all_wins = [t for t in trailing_trades if t.get("pnl_pct", 0) > 0]
        p = len(all_wins) / max(1, len(trailing_trades)) if trailing_trades else 0.5
        avg_win = sum(t["pnl_pct"] for t in all_wins) / max(1, len(all_wins)) if all_wins else 0.03
        losses = [t for t in trailing_trades if t.get("pnl_pct", 0) <= 0]
        avg_loss = abs(sum(t["pnl_pct"] for t in losses) / max(1, len(losses))) if losses else 0.02
        confidence_penalty = 0.5
    else:
        wins = [t for t in regime_trades if t.get("pnl_pct", 0) > 0]
        p = len(wins) / len(regime_trades)
        avg_win = sum(t["pnl_pct"] for t in wins) / max(1, len(wins)) if wins else 0.03
        losses = [t for t in regime_trades if t.get("pnl_pct", 0) <= 0]
        avg_loss = abs(sum(t["pnl_pct"] for t in losses) / max(1, len(losses))) if losses else 0.02
        confidence_penalty = 1.0

    q = 1 - p
    b = avg_win / max(0.001, avg_loss)

    if (p * b - q) <= 0:
        return {
            "kelly_fraction": 0.0,
            "sizing_mode": sizing_mode,
            "reason": "Negative expected value in current regime",
            "full_kelly": 0.0,
            "half_kelly": 0.0,
            "win_rate": round(p, 3),
            "win_loss_ratio": round(b, 3),
        }

    full_kelly = (p * b - q) / b
    divisor = KELLY_DIVISORS.get(sizing_mode, 4.0)
    fractional_kelly = full_kelly / divisor
    adjusted_kelly = fractional_kelly * confidence_penalty
    vol_adjusted = adjusted_kelly * vol.position_scale

    if portfolio_correlation > 0.6:
        corr_haircut = 1.0 - (portfolio_correlation - 0.6) * 1.5
        vol_adjusted *= max(0.4, corr_haircut)

    cap = STRATEGY_CAPS.get(strategy, 0.05)
    final_size = min(vol_adjusted, cap)

    return {
        "kelly_fraction": round(final_size, 4),
        "sizing_mode": sizing_mode,
        "full_kelly": round(full_kelly, 4),
        "half_kelly": round(full_kelly / 2.0, 4),
        "fractional_kelly": round(fractional_kelly, 4),
        "win_rate": round(p, 3),
        "win_loss_ratio": round(b, 3),
        "vol_scale_applied": round(vol.position_scale, 3),
        "corr_haircut_applied": round(portfolio_correlation, 3),
        "regime_trades_count": len(regime_trades),
        "confidence_penalty": confidence_penalty,
    }


def _equal_risk_sizing(
    strategy: str,
    vol: VolContext,
    stop_distance_pct: float,
) -> dict:
    """Fixed risk-budget sizing: risk X% of capital per trade.

    position_size = risk_per_trade / stop_distance
    E.g., 1% risk with a 3% stop -> 33% position size (before caps).
    """
    risk_per_trade = settings.equal_risk_per_trade_pct
    if stop_distance_pct > 0:
        raw_size = risk_per_trade / stop_distance_pct
    else:
        raw_size = risk_per_trade

    vol_adjusted = raw_size * vol.position_scale
    cap = STRATEGY_CAPS.get(strategy, 0.05)
    final_size = min(vol_adjusted, cap)

    return {
        "kelly_fraction": round(final_size, 4),
        "sizing_mode": "equal_risk",
        "risk_per_trade_pct": risk_per_trade,
        "stop_distance_pct": round(stop_distance_pct, 4),
        "raw_size": round(raw_size, 4),
        "full_kelly": 0.0,
        "half_kelly": 0.0,
        "fractional_kelly": 0.0,
        "win_rate": 0.0,
        "win_loss_ratio": 0.0,
        "vol_scale_applied": round(vol.position_scale, 3),
        "corr_haircut_applied": 0.0,
        "regime_trades_count": 0,
        "confidence_penalty": 1.0,
    }

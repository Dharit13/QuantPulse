"""Volatility-scaled risk limits.

Principle: keep the DOLLAR VAR approximately constant across regimes.
If vol doubles, position sizes halve -> same dollar risk.
"""

from backend.adaptive.vol_context import VolContext


def get_adaptive_risk_limits(vol: VolContext) -> dict:
    ps = vol.position_scale

    return {
        "max_position_pct": round(0.08 * ps, 3),
        "max_gross_exposure": round(min(2.5, 2.0 * ps), 2),
        "reduce_at_drawdown_pct": round(-0.10 * min(1.0, ps), 3),
        "flatten_at_drawdown_pct": round(-0.15 * min(1.0, ps), 3),
        "daily_var_limit_pct": round(0.02 * ps, 3),
        "max_sector_pct": (
            0.15 if vol.correlation_regime == "herding"
            else 0.20 if vol.correlation_regime == "normal"
            else 0.30
        ),
        "tail_hedge_pct": (
            0.05 if vol.vol_regime.value in ("ultra_low", "low")
            else 0.03 if vol.vol_regime.value == "normal"
            else 0.02 if vol.vol_regime.value == "elevated"
            else 0.01
        ),
        "max_position_correlation": (
            0.60 if vol.correlation_regime == "herding"
            else 0.75 if vol.correlation_regime == "normal"
            else 0.85
        ),
    }

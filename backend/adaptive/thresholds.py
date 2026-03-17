"""Adaptive entry/exit thresholds for all strategies.

All thresholds are expressed as: adaptive_threshold = base_threshold x vol_scale.
In low vol, thresholds tighten. In high vol, they widen.
"""

from backend.adaptive.vol_context import VolContext, VolRegime


def get_stat_arb_params(vol: VolContext) -> dict:
    vs = vol.vol_scale
    ps = vol.position_scale

    return {
        "entry_z": 2.0 * max(0.8, min(2.5, vs)),
        "exit_z": 0.5 * max(0.8, min(1.5, vs)),
        "stop_z": 3.5 * max(0.8, min(2.0, vs)),
        "max_position_pct": 0.04 * ps,
        "max_strategy_pct": 0.20 * ps,
        "max_hold_days": int(20 / max(0.5, vol.speed_scale)),
        "min_adf_pvalue": 0.01 if vs < 1.5 else 0.005,
        "min_half_life_days": max(2, int(3 / vol.speed_scale)),
        "max_half_life_days": int(30 / max(0.5, vol.speed_scale)),
    }


def get_catalyst_params(vol: VolContext) -> dict:
    vs = vol.vol_scale
    ps = vol.position_scale

    return {
        "min_eps_surprise_pct": 5.0 * max(1.0, vs * 0.8),
        "min_earnings_gap_pct": 2.0 * max(0.8, vs * 0.7),
        "stop_loss_pct": 5.0 * max(0.8, min(2.0, vs)),
        "target_return_pct": 10.0 * max(0.8, min(1.5, vs)),
        "max_hold_days": int(40 / max(0.7, vol.speed_scale)),
        "max_position_pct": 0.06 * ps,
        "min_breadth": 0.3 if vs < 1.3 else 0.4,
        "min_acceleration": 0.1 if vs < 1.3 else 0.15,
    }


def get_cross_asset_params(vol: VolContext) -> dict:
    vs = vol.vol_scale

    if vol.vol_regime == VolRegime.EXTREME:
        active = ["vix_term", "credit_spread"]
    elif vol.vol_regime in (VolRegime.HIGH, VolRegime.ELEVATED):
        active = ["vix_term", "credit_spread", "yield_curve", "oil", "dollar", "copper_gold"]
    else:
        active = "all"

    return {
        "signal_z_threshold": 1.5 * max(0.7, min(2.0, vs)),
        "max_hold_days": int(15 / max(0.5, vol.speed_scale)),
        "active_signals": active,
    }


def get_gap_reversion_params(vol: VolContext) -> dict:
    vs = vol.vol_scale

    return {
        "min_gap_pct": max(0.7, 1.0 * vs),
        "max_gap_pct": max(3.0, 5.0 * vs),
        "stop_pct_of_gap": 0.5 * max(0.8, min(1.5, vs)),
        "close_by_time": "11:00" if vs < 1.3 else "10:30",
        "max_vix_for_trading": 30,
        "max_position_pct": 0.02 * vol.position_scale,
    }


def get_flow_params(vol: VolContext) -> dict:
    vs = vol.vol_scale

    return {
        "min_sweep_premium": 100_000 * max(1.0, vs),
        "min_dark_pool_notional": 1_000_000 * max(1.0, vs),
        "max_hold_days": int(10 / max(0.5, vol.speed_scale)),
        "stop_loss_pct": 3.0 * max(0.8, min(2.0, vs)),
        "gex_significance_threshold": "auto",
    }

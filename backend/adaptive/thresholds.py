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

    active: list[str] | str
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


def get_sentiment_scoring_params(vol: VolContext) -> dict:
    """Adaptive sentiment nudge for stock scoring.

    High vol → sentiment is noise, reduce impact. Low vol → sentiment
    is more meaningful signal, increase impact.
    """
    ps = vol.position_scale

    base_bullish = 5.0
    base_bearish = 5.0

    return {
        "bullish_nudge": round(base_bullish * min(1.5, ps), 1),
        "bearish_nudge": round(base_bearish * min(1.5, ps), 1),
    }


def get_portfolio_waterfall_params(vol: VolContext) -> dict:
    """Adaptive portfolio pick-selection parameters.

    High vol → lower sentiment bar (fewer bullish tickers exist), more picks
    for diversification, stricter sector limits.
    Low vol → higher sentiment bar (be selective), fewer concentrated picks,
    allow sector concentration.
    """
    from backend.config import settings

    vs = vol.vol_scale
    ps = vol.position_scale  # inverse vol: small in high vol, large in low vol

    base_sent = settings.portfolio_sentiment_min_score
    base_max_sent = settings.portfolio_max_sentiment_candidates
    base_sector = settings.portfolio_max_per_sector
    base_max = settings.portfolio_max_picks
    base_min = settings.portfolio_min_candidates

    return {
        # Lower bar in high vol (fewer bullish names), raise in low vol
        "sentiment_min_score": max(50.0, base_sent * min(1.2, 1.0 / max(0.7, vs))),
        # More sentiment candidates in high vol for diversification
        "max_sentiment_candidates": max(3, int(base_max_sent * max(0.8, min(1.5, vs)))),
        # Stricter sector limits in high vol (force diversification)
        "max_per_sector": max(1, round(base_sector * min(1.5, ps))),
        # More picks in high vol for diversification, fewer in calm markets
        "max_picks": max(base_min, min(8, round(base_max * max(0.8, min(1.4, vs))))),
        # Minimum always honoured
        "min_candidates": base_min,
    }

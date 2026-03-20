"""Regime detection endpoint — current regime + history."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Query

from backend.data.cache import data_cache
from backend.models.database import get_supabase
from backend.models.schemas import Regime, RegimeSnapshot

router = APIRouter(prefix="/regime", tags=["regime"])
logger = logging.getLogger(__name__)


def _get_strategy_health(regime_value: str | None) -> dict[str, dict]:
    """Compute health status for each strategy."""
    from backend.models.schemas import StrategyName
    from backend.tracker.strategy_health import compute_strategy_health

    regime_str = regime_value
    if hasattr(regime_str, "value"):
        regime_str = regime_str.value

    health_map: dict[str, dict] = {}
    for strat in StrategyName:
        try:
            h = compute_strategy_health(strat.value, current_regime=regime_str)
            health_map[strat.value] = {
                "status": h.status,
                "sharpe_60d": h.rolling_sharpe_60d,
                "win_rate_60d": h.rolling_win_rate_60d,
            }
        except Exception:
            health_map[strat.value] = {"status": "unknown", "sharpe_60d": 0.0, "win_rate_60d": 0.0}
    return health_map


def _get_strategy_activity() -> dict[str, dict]:
    """Extract strategy signal counts from the last scanner result."""
    cached_scan = data_cache.get("scanner:last_result")
    if not cached_scan or not isinstance(cached_scan, dict):
        return {}

    activity: dict[str, dict] = {}
    signals = cached_scan.get("signals", [])
    if isinstance(cached_scan.get("data"), dict):
        signals = cached_scan["data"].get("signals", signals)

    for sig_data in signals:
        sig = sig_data.get("signal", sig_data) if isinstance(sig_data, dict) else sig_data
        strat = sig.get("strategy", "unknown") if isinstance(sig, dict) else "unknown"
        if strat not in activity:
            activity[strat] = {"signal_count": 0, "active": True}
        activity[strat]["signal_count"] += 1

    return activity


@router.get("/current")
async def get_current_regime(
    refresh: bool = Query(False, description="Force live computation, bypass pipeline cache"),
) -> dict:
    """Return the current market regime from pipeline cache (instant) or live."""
    result = None
    if not refresh:
        cached = data_cache.get("pipeline:regime")
        if cached and isinstance(cached, dict):
            result = cached

    if result is None:
        from backend.pipeline import refresh_regime

        result = refresh_regime()

    if not result:
        return {"error": "Regime detection failed", "regime": "unknown"}

    result["strategy_activity"] = _get_strategy_activity()
    result["strategy_health"] = _get_strategy_health(result.get("regime"))
    return result


@router.get("/history", response_model=list[RegimeSnapshot])
async def get_regime_history(limit: int = Query(default=30, ge=1, le=365)) -> list[RegimeSnapshot]:
    """Return recent regime snapshots from the database."""
    sb = get_supabase()
    result = sb.table("regimes").select("*").order("timestamp", desc=True).limit(limit).execute()
    return [
        RegimeSnapshot(
            timestamp=r["timestamp"],
            regime=Regime(r["regime"]),
            confidence=r["confidence"],
            regime_probabilities=json.loads(r["regime_probabilities_json"]),
            vix=r["vix"],
            breadth_pct=r["breadth_pct"],
            adx=r["adx"],
            strategy_weights=json.loads(r["strategy_weights_json"]),
        )
        for r in result.data
    ]

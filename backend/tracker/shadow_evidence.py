"""Shadow evidence engine — how have similar signals performed?

Queries closed phantom trades to compute win rate, Sharpe, hold time,
and return stats for signals matching the current strategy/direction/regime.
Pure DB query — fast, no API calls.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from backend.models.database import get_supabase

logger = logging.getLogger(__name__)

MIN_PHANTOMS_FOR_EVIDENCE = 10


@dataclass
class ShadowEvidence:
    phantom_count: int
    win_rate: float
    avg_pnl_pct: float
    avg_hold_days: float
    realized_sharpe: float
    best_trade_pct: float
    worst_trade_pct: float
    has_enough_data: bool


def get_similar_signal_evidence(
    strategy: str,
    direction: str,
    regime: str | None = None,
    lookback_days: int = 90,
    min_score: float = 0.0,
) -> ShadowEvidence:
    """Query closed phantoms matching the given filters and compute stats."""
    cutoff = str(date.today() - timedelta(days=lookback_days))

    sb = get_supabase()
    q = (
        sb.table("phantom_trades")
        .select("*")
        .eq("strategy", strategy)
        .eq("direction", direction)
        .gte("signal_date", cutoff)
        .not_.is_("phantom_outcome", "null")
    )

    if regime:
        q = q.eq("regime", regime)

    if min_score > 0:
        q = q.gte("signal_score", min_score)

    result = q.execute()
    phantoms = result.data

    if not phantoms:
        return _empty_evidence()

    pnl_values = [p["phantom_pnl_pct"] for p in phantoms if p.get("phantom_pnl_pct") is not None]
    if not pnl_values:
        return _empty_evidence()

    wins = [p for p in phantoms if p.get("phantom_outcome") == "would_have_won"]
    win_rate = len(wins) / len(phantoms) if phantoms else 0.0

    hold_days_list = []
    for p in phantoms:
        if p.get("phantom_exit_date") and p.get("signal_date"):
            exit_d = (
                date.fromisoformat(p["phantom_exit_date"])
                if isinstance(p["phantom_exit_date"], str)
                else p["phantom_exit_date"]
            )
            sig_d = date.fromisoformat(p["signal_date"]) if isinstance(p["signal_date"], str) else p["signal_date"]
            days = (exit_d - sig_d).days
            hold_days_list.append(max(1, days))

    avg_hold = float(np.mean(hold_days_list)) if hold_days_list else 0.0

    arr = np.array(pnl_values)
    avg_pnl = float(arr.mean())
    std_pnl = float(arr.std()) if len(arr) > 1 else 1.0
    realized_sharpe = float(avg_pnl / std_pnl * np.sqrt(252)) if std_pnl > 0 else 0.0

    return ShadowEvidence(
        phantom_count=len(phantoms),
        win_rate=round(win_rate, 3),
        avg_pnl_pct=round(avg_pnl, 4),
        avg_hold_days=round(avg_hold, 1),
        realized_sharpe=round(realized_sharpe, 2),
        best_trade_pct=round(float(arr.max()), 4),
        worst_trade_pct=round(float(arr.min()), 4),
        has_enough_data=len(phantoms) >= MIN_PHANTOMS_FOR_EVIDENCE,
    )


def _empty_evidence() -> ShadowEvidence:
    return ShadowEvidence(
        phantom_count=0,
        win_rate=0.0,
        avg_pnl_pct=0.0,
        avg_hold_days=0.0,
        realized_sharpe=0.0,
        best_trade_pct=0.0,
        worst_trade_pct=0.0,
        has_enough_data=False,
    )

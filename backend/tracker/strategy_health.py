"""Strategy health monitor — is this strategy still working?

Computes rolling Sharpe, win rate, and degradation signals from
phantom trade outcomes. Determines whether a strategy should run
at full size, reduced size, or be paused.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from backend.adaptive.weight_interpolation import STRATEGY_WEIGHTS
from backend.models.database import PhantomTradeRecord, SessionLocal

logger = logging.getLogger(__name__)

SHARPE_HEALTHY = 0.5
SHARPE_PAUSED = 0.0
MIN_PHANTOMS_FOR_HEALTH = 5


@dataclass
class StrategyHealth:
    status: str
    rolling_sharpe_60d: float
    rolling_win_rate_60d: float
    phantom_count_60d: int
    avg_slippage_vs_model: float
    borrow_failure_rate: float
    slippage_deteriorating: bool
    regime_alignment: str
    size_adjustment: float


def compute_strategy_health(
    strategy: str,
    current_regime: str | None = None,
    lookback_days: int = 60,
) -> StrategyHealth:
    """Assess whether a strategy is healthy, degraded, or should be paused."""
    cutoff = date.today() - timedelta(days=lookback_days)

    with SessionLocal() as db:
        phantoms = (
            db.query(PhantomTradeRecord)
            .filter(
                PhantomTradeRecord.strategy == strategy,
                PhantomTradeRecord.signal_date >= cutoff,
                PhantomTradeRecord.phantom_outcome.isnot(None),
            )
            .all()
        )

    if len(phantoms) < MIN_PHANTOMS_FOR_HEALTH:
        return StrategyHealth(
            status="insufficient_data",
            rolling_sharpe_60d=0.0,
            rolling_win_rate_60d=0.0,
            phantom_count_60d=len(phantoms),
            avg_slippage_vs_model=0.0,
            borrow_failure_rate=0.0,
            slippage_deteriorating=False,
            regime_alignment=_regime_alignment(strategy, current_regime),
            size_adjustment=0.8,
        )

    pnl_values = [p.phantom_pnl_pct for p in phantoms if p.phantom_pnl_pct is not None]
    wins = [p for p in phantoms if p.phantom_outcome == "would_have_won"]

    win_rate = len(wins) / len(phantoms)

    arr = np.array(pnl_values) if pnl_values else np.array([0.0])
    mean_pnl = float(arr.mean())
    std_pnl = float(arr.std()) if len(arr) > 1 else 1.0
    sharpe = float(mean_pnl / std_pnl * np.sqrt(252)) if std_pnl > 0 else 0.0

    # Determine status and size adjustment
    if sharpe < SHARPE_PAUSED:
        status = "paused"
        size_adj = 0.0
    elif sharpe < SHARPE_HEALTHY:
        status = "degraded"
        size_adj = 0.5
    else:
        status = "healthy"
        size_adj = 1.0

    alignment = _regime_alignment(strategy, current_regime)
    if alignment == "unfavorable":
        size_adj *= 0.7

    # Slippage deterioration: compare first half vs second half of phantom PnLs
    slippage_deteriorating = False
    if len(pnl_values) >= 10:
        mid = len(pnl_values) // 2
        first_half_avg = float(np.mean(pnl_values[:mid]))
        second_half_avg = float(np.mean(pnl_values[mid:]))
        if second_half_avg < first_half_avg * 0.7:
            slippage_deteriorating = True

    return StrategyHealth(
        status=status,
        rolling_sharpe_60d=round(sharpe, 2),
        rolling_win_rate_60d=round(win_rate, 3),
        phantom_count_60d=len(phantoms),
        avg_slippage_vs_model=0.0,
        borrow_failure_rate=0.0,
        slippage_deteriorating=slippage_deteriorating,
        regime_alignment=alignment,
        size_adjustment=round(size_adj, 2),
    )


def _regime_alignment(strategy: str, regime: str | None) -> str:
    """Check if the strategy gets meaningful allocation in the current regime."""
    if not regime or regime not in STRATEGY_WEIGHTS:
        return "neutral"

    weights = STRATEGY_WEIGHTS[regime]
    strategy_key_map = {
        "stat_arb": "stat_arb",
        "catalyst": "catalyst",
        "cross_asset": "momentum",
        "flow": "flow",
        "intraday": "intraday",
    }
    key = strategy_key_map.get(strategy, strategy)
    weight = weights.get(key, 0.1)

    if weight >= 0.20:
        return "favorable"
    elif weight >= 0.10:
        return "neutral"
    return "unfavorable"

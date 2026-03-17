"""Per-strategy performance attribution.

Breaks down P&L, win rate, Sharpe, and contribution by strategy so the
user can see which engines are earning and which are bleeding.  Also
computes judgment-vs-model metrics (signals taken vs phantoms).
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import date

import numpy as np

from backend.models.schemas import PerformanceStats, StrategyName, TradeEntry
from backend.tracker.trade_journal import TradeJournal

logger = logging.getLogger(__name__)


class StrategyPerformanceTracker:
    """Compute per-strategy and aggregate performance from the trade journal."""

    def __init__(self, journal: TradeJournal | None = None):
        self.journal = journal or TradeJournal()

    def overall_stats(self, since: date | None = None) -> PerformanceStats:
        """Aggregate stats across all strategies."""
        trades = self.journal.get_closed_trades(since=since)
        breakdown = self._per_strategy_breakdown(trades)
        agg = self._aggregate(trades)
        return PerformanceStats(
            total_pnl_dollars=agg["total_pnl_dollars"],
            total_pnl_pct=agg["total_pnl_pct"],
            win_rate=agg["win_rate"],
            avg_win_pct=agg["avg_win_pct"],
            avg_loss_pct=agg["avg_loss_pct"],
            profit_factor=agg["profit_factor"],
            total_trades=agg["total_trades"],
            sharpe_ratio=agg["sharpe_ratio"],
            max_drawdown_pct=agg["max_drawdown_pct"],
            strategy_breakdown=breakdown,
        )

    def strategy_stats(self, strategy: StrategyName, since: date | None = None) -> dict:
        """Stats for a single strategy."""
        trades = self.journal.get_closed_trades(strategy=strategy, since=since)
        return self._aggregate(trades)

    def judgment_vs_model(self, since: date | None = None) -> dict:
        """Compare trades taken vs signals passed (phantoms)."""
        taken = self.journal.get_closed_trades(since=since)
        phantoms = self.journal.get_phantom_trades(since=since)
        resolved_phantoms = [p for p in phantoms if p.phantom_pnl_pct is not None]

        taken_wins = [t for t in taken if t.pnl_percent and t.pnl_percent > 0]
        phantom_wins = [p for p in resolved_phantoms if p.phantom_pnl_pct and p.phantom_pnl_pct > 0]

        taken_pnl = sum(t.pnl_dollars or 0 for t in taken)
        phantom_pnl = sum(
            p.phantom_pnl_pct / 100 * p.entry_price_suggested
            for p in resolved_phantoms
            if p.phantom_pnl_pct is not None
        )

        taken_wr = len(taken_wins) / len(taken) if taken else 0
        phantom_wr = len(phantom_wins) / len(resolved_phantoms) if resolved_phantoms else 0

        return {
            "trades_taken": len(taken),
            "trades_taken_win_rate": round(taken_wr, 4),
            "trades_taken_pnl": round(taken_pnl, 2),
            "signals_passed": len(phantoms),
            "signals_passed_resolved": len(resolved_phantoms),
            "phantom_win_rate": round(phantom_wr, 4),
            "phantom_pnl_estimate": round(phantom_pnl, 2),
            "judgment_alpha_pct": round((taken_wr - phantom_wr) * 100, 2) if resolved_phantoms else None,
            "missed_profit": round(
                sum(p.phantom_pnl_pct for p in phantom_wins if p.phantom_pnl_pct and p.phantom_pnl_pct > 0), 2
            ),
        }

    def contribution_breakdown(self, since: date | None = None) -> dict[str, float]:
        """Each strategy's fractional contribution to total P&L."""
        trades = self.journal.get_closed_trades(since=since)
        total_pnl = sum(t.pnl_dollars or 0 for t in trades)
        if total_pnl == 0:
            return {}
        by_strat: dict[str, float] = defaultdict(float)
        for t in trades:
            by_strat[t.strategy.value if isinstance(t.strategy, StrategyName) else t.strategy] += t.pnl_dollars or 0
        return {k: round(v / total_pnl, 4) for k, v in by_strat.items()}

    # ── Internal ────────────────────────────────────────────────

    def _per_strategy_breakdown(self, trades: list[TradeEntry]) -> dict[str, dict]:
        grouped: dict[str, list[TradeEntry]] = defaultdict(list)
        for t in trades:
            key = t.strategy.value if isinstance(t.strategy, StrategyName) else t.strategy
            grouped[key].append(t)
        return {name: self._aggregate(tlist) for name, tlist in grouped.items()}

    @staticmethod
    def _aggregate(trades: list[TradeEntry]) -> dict:
        if not trades:
            return {
                "total_trades": 0, "win_rate": 0, "total_pnl_dollars": 0,
                "total_pnl_pct": 0, "avg_win_pct": 0, "avg_loss_pct": 0,
                "profit_factor": 0, "sharpe_ratio": 0, "max_drawdown_pct": 0,
            }

        wins = [t for t in trades if t.pnl_percent and t.pnl_percent > 0]
        losses = [t for t in trades if t.pnl_percent and t.pnl_percent <= 0]
        returns = [t.pnl_percent for t in trades if t.pnl_percent is not None]

        total_pnl = sum(t.pnl_dollars or 0 for t in trades)
        gross_win = sum(t.pnl_dollars for t in wins if t.pnl_dollars)
        gross_loss = abs(sum(t.pnl_dollars for t in losses if t.pnl_dollars))

        ret_arr = np.array(returns) if returns else np.array([0.0])
        sharpe = float(ret_arr.mean() / ret_arr.std() * math.sqrt(252)) if ret_arr.std() > 0 else 0.0

        cumulative = np.cumsum(ret_arr)
        peak = np.maximum.accumulate(cumulative)
        drawdowns = cumulative - peak
        max_dd = float(drawdowns.min()) if len(drawdowns) > 0 else 0.0

        return {
            "total_trades": len(trades),
            "win_rate": round(len(wins) / len(trades), 4),
            "total_pnl_dollars": round(total_pnl, 2),
            "total_pnl_pct": round(sum(returns), 4) if returns else 0,
            "avg_win_pct": round(sum(t.pnl_percent for t in wins if t.pnl_percent) / max(len(wins), 1), 4),
            "avg_loss_pct": round(sum(t.pnl_percent for t in losses if t.pnl_percent) / max(len(losses), 1), 4),
            "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else 99.99,
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown_pct": round(max_dd, 4),
        }

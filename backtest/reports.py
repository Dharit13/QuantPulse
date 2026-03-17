"""Backtest tear sheet / report generation.

Takes a BacktestResult and produces structured data suitable for
Streamlit rendering (Sprint 5) or CLI inspection.

Outputs:
  - Summary statistics table
  - Monthly / yearly return grid
  - Drawdown analysis with recovery periods
  - Per-regime performance breakdown
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

import numpy as np

from backend.models.schemas import BacktestResult, BacktestTrade, PerformanceStats


def generate_tear_sheet(result: BacktestResult) -> dict:
    """Master function — builds the full report dict."""
    return {
        "summary": _summary_stats(result),
        "monthly_returns": result.monthly_returns,
        "yearly_returns": _yearly_returns(result.trades),
        "drawdown_analysis": _drawdown_analysis(result.equity_curve),
        "regime_performance": _regime_performance(result),
        "trade_analysis": _trade_analysis(result.trades),
        "validation": result.validation,
    }


def to_performance_stats(result: BacktestResult) -> PerformanceStats:
    """Convert BacktestResult into the standard PerformanceStats model."""
    return PerformanceStats(
        total_pnl_dollars=round(result.total_return_pct * result.config.initial_capital, 2),
        total_pnl_pct=result.total_return_pct,
        win_rate=result.win_rate,
        avg_win_pct=result.avg_win_pct,
        avg_loss_pct=result.avg_loss_pct,
        profit_factor=result.profit_factor,
        total_trades=result.total_trades,
        sharpe_ratio=result.sharpe_ratio,
        max_drawdown_pct=result.max_drawdown_pct,
        strategy_breakdown={result.strategy.value: {
            "trades": result.total_trades,
            "sharpe": result.sharpe_ratio,
            "win_rate": result.win_rate,
            "cagr": result.cagr_pct,
        }},
    )


# ── Private helpers ──


def _summary_stats(result: BacktestResult) -> dict:
    return {
        "strategy": result.strategy.value,
        "total_return_pct": result.total_return_pct,
        "cagr_pct": result.cagr_pct,
        "sharpe_ratio": result.sharpe_ratio,
        "sortino_ratio": result.sortino_ratio,
        "win_rate": result.win_rate,
        "avg_win_pct": result.avg_win_pct,
        "avg_loss_pct": result.avg_loss_pct,
        "profit_factor": result.profit_factor,
        "max_drawdown_pct": result.max_drawdown_pct,
        "total_trades": result.total_trades,
        "avg_hold_days": result.avg_hold_days,
        "initial_capital": result.config.initial_capital,
        "final_equity": (
            result.equity_curve[-1]["equity"]
            if result.equity_curve
            else result.config.initial_capital
        ),
    }


def _yearly_returns(trades: list[BacktestTrade]) -> list[dict]:
    if not trades:
        return []

    by_year: dict[int, float] = defaultdict(float)
    for t in trades:
        by_year[t.exit_date.year] += t.pnl_pct

    return [
        {"year": y, "return_pct": round(r, 4)}
        for y, r in sorted(by_year.items())
    ]


def _drawdown_analysis(equity_curve: list[dict]) -> dict:
    """Identify the top-5 drawdown episodes with duration and recovery."""
    if not equity_curve:
        return {"max_drawdown_pct": 0.0, "episodes": []}

    equities = [e["equity"] for e in equity_curve]
    dates = [e["date"] for e in equity_curve]

    peak = equities[0]
    peak_idx = 0
    episodes: list[dict] = []
    current_dd_start: int | None = None

    for i, eq in enumerate(equities):
        if eq >= peak:
            if current_dd_start is not None:
                trough_idx = current_dd_start + int(
                    np.argmin(equities[current_dd_start : i + 1])
                )
                dd_pct = (equities[trough_idx] - equities[peak_idx]) / equities[peak_idx]
                episodes.append({
                    "start_date": dates[peak_idx],
                    "trough_date": dates[trough_idx],
                    "recovery_date": dates[i],
                    "drawdown_pct": round(dd_pct, 4),
                    "duration_days": i - peak_idx,
                    "recovery_days": i - trough_idx,
                })
                current_dd_start = None
            peak = eq
            peak_idx = i
        else:
            if current_dd_start is None:
                current_dd_start = i

    # Handle ongoing drawdown at end of curve
    if current_dd_start is not None:
        trough_idx = current_dd_start + int(
            np.argmin(equities[current_dd_start:])
        )
        dd_pct = (equities[trough_idx] - equities[peak_idx]) / equities[peak_idx]
        episodes.append({
            "start_date": dates[peak_idx],
            "trough_date": dates[trough_idx],
            "recovery_date": None,
            "drawdown_pct": round(dd_pct, 4),
            "duration_days": len(equities) - peak_idx,
            "recovery_days": None,
        })

    episodes.sort(key=lambda x: x["drawdown_pct"])
    top_episodes = episodes[:5]

    max_dd = min((e["drawdown_pct"] for e in episodes), default=0.0)

    return {
        "max_drawdown_pct": round(max_dd, 4),
        "episodes": top_episodes,
    }


def _regime_performance(result: BacktestResult) -> dict:
    """Break down performance by the regime field if available.

    Currently returns the pre-computed regime_performance from the
    BacktestResult. Future versions will cross-reference trade dates
    with regime history.
    """
    return result.regime_performance


def _trade_analysis(trades: list[BacktestTrade]) -> dict:
    if not trades:
        return {}

    pnls = [t.pnl_pct for t in trades]
    holds = [t.hold_days for t in trades]

    by_exit: dict[str, int] = defaultdict(int)
    for t in trades:
        by_exit[t.exit_reason] += 1

    # Win/loss streaks
    streak = 0
    max_win_streak = 0
    max_loss_streak = 0
    for p in pnls:
        if p > 0:
            streak = max(1, streak + 1) if streak > 0 else 1
            max_win_streak = max(max_win_streak, streak)
        else:
            streak = min(-1, streak - 1) if streak < 0 else -1
            max_loss_streak = max(max_loss_streak, abs(streak))

    return {
        "avg_pnl_pct": round(float(np.mean(pnls)), 4),
        "median_pnl_pct": round(float(np.median(pnls)), 4),
        "std_pnl_pct": round(float(np.std(pnls)), 4),
        "avg_hold_days": round(float(np.mean(holds)), 1),
        "median_hold_days": round(float(np.median(holds)), 1),
        "exit_reason_counts": dict(by_exit),
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "best_trade_pct": round(float(max(pnls)), 4),
        "worst_trade_pct": round(float(min(pnls)), 4),
    }

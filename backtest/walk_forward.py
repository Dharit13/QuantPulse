"""Walk-Forward Backtest Engine.

Runs any BaseStrategy subclass through rolling train/test windows using
purely out-of-sample evaluation. The engine does NOT optimise parameters
— each strategy's adaptive logic (driven by VolContext) handles that.

Protocol (from spec Section 15):
  1. Split data into N windows (train_days + test_days, rolling).
  2. For each window the strategy generates signals on the test period
     with a VolContext computed from the trailing data.
  3. Signals are filled at next-bar open with transaction costs.
  4. Final performance = concatenation of ALL out-of-sample periods.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from backend.adaptive.vol_context import VolContext, compute_vol_context
from backend.models.schemas import (
    BacktestConfig,
    BacktestResult,
    BacktestTrade,
    StrategyName,
    TradeSignal,
)
from backend.strategies.base import BaseStrategy
from backtest.transaction_costs import TransactionCostModel, default_cost_model

logger = logging.getLogger(__name__)


# ── Internal bookkeeping ──


@dataclass
class _OpenPosition:
    ticker: str
    direction: str
    strategy: StrategyName
    entry_date: date
    entry_price: float
    shares: int
    position_size_pct: float
    stop_loss: float
    target: float
    max_hold_days: int
    conviction: float
    signal_score: float
    bars_held: int = 0


@dataclass
class _EquityPoint:
    date: date
    equity: float
    drawdown_pct: float


# ── Engine ──


class WalkForwardEngine:
    """Walk-forward backtest runner.

    Accepts pre-fetched price DataFrames so the engine itself never
    hits the network — keeps backtests deterministic and fast.
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        config: BacktestConfig | None = None,
        cost_model: TransactionCostModel | None = None,
    ):
        self.strategy = strategy
        self.config = config or BacktestConfig()
        self.cost_model = cost_model or default_cost_model

    def run(
        self,
        price_data: dict[str, pd.DataFrame],
        spy_df: pd.DataFrame,
        vix_df: pd.DataFrame,
        strategy_kwargs: dict | None = None,
    ) -> BacktestResult:
        """Execute the full walk-forward backtest.

        Args:
            price_data: ticker → OHLCV DataFrame (DatetimeIndex).
            spy_df: SPY OHLCV for VolContext computation.
            vix_df: VIX OHLCV for VolContext computation.
            strategy_kwargs: extra kwargs forwarded to generate_signals().
        """
        strategy_kwargs = strategy_kwargs or {}

        all_dates = spy_df.index.normalize().unique().sort_values()
        n_dates = len(all_dates)
        train = self.config.train_days
        test = self.config.test_days
        window_size = train + test

        if n_dates < window_size:
            raise ValueError(
                f"Need at least {window_size} trading days, got {n_dates}"
            )

        all_trades: list[BacktestTrade] = []
        equity = self.config.initial_capital
        peak_equity = equity
        equity_curve: list[dict] = []

        window_start = 0
        while window_start + window_size <= n_dates:
            train_end_idx = window_start + train
            test_end_idx = window_start + window_size

            train_dates = all_dates[window_start:train_end_idx]
            test_dates = all_dates[train_end_idx:test_end_idx]

            vol = self._build_vol_context(spy_df, vix_df, train_dates)

            window_trades, equity, peak_equity = self._run_test_window(
                test_dates=test_dates,
                price_data=price_data,
                vol=vol,
                equity=equity,
                peak_equity=peak_equity,
                equity_curve=equity_curve,
                strategy_kwargs=strategy_kwargs,
            )
            all_trades.extend(window_trades)

            window_start += test

        return self._compile_result(all_trades, equity_curve)

    # ── Private helpers ──

    def _build_vol_context(
        self,
        spy_df: pd.DataFrame,
        vix_df: pd.DataFrame,
        train_dates: pd.DatetimeIndex,
    ) -> VolContext:
        start, end = train_dates[0], train_dates[-1]
        spy_slice = spy_df.loc[start:end]
        vix_slice = vix_df.loc[start:end]
        return compute_vol_context(spy_slice, vix_slice)

    def _run_test_window(
        self,
        test_dates: pd.DatetimeIndex,
        price_data: dict[str, pd.DataFrame],
        vol: VolContext,
        equity: float,
        peak_equity: float,
        equity_curve: list[dict],
        strategy_kwargs: dict,
    ) -> tuple[list[BacktestTrade], float, float]:
        """Simulate trading over one test window."""
        open_positions: list[_OpenPosition] = []
        closed_trades: list[BacktestTrade] = []

        signals = self.strategy.generate_signals(vol, **strategy_kwargs)

        for bar_date in test_dates:
            dt = bar_date.date() if hasattr(bar_date, "date") else bar_date

            # 1. Check exits on existing positions
            to_close: list[int] = []
            for i, pos in enumerate(open_positions):
                ticker_df = price_data.get(pos.ticker)
                if ticker_df is None or bar_date not in ticker_df.index:
                    continue

                bar = ticker_df.loc[bar_date]
                pos.bars_held += 1
                exit_price, exit_reason = self._check_exit(pos, bar)

                if exit_price is not None:
                    trade = self._close_position(
                        pos, dt, exit_price, exit_reason, vol.vol_scale
                    )
                    equity += trade.pnl_dollars
                    peak_equity = max(peak_equity, equity)
                    closed_trades.append(trade)
                    to_close.append(i)

            for idx in sorted(to_close, reverse=True):
                open_positions.pop(idx)

            # 2. Open new positions from signals not yet entered
            for sig in signals:
                if self._already_in(sig.ticker, open_positions):
                    continue

                ticker_df = price_data.get(sig.ticker)
                if ticker_df is None or bar_date not in ticker_df.index:
                    continue

                bar = ticker_df.loc[bar_date]
                fill_price = float(bar["Open"])
                if fill_price <= 0:
                    continue

                size_pct = min(sig.kelly_size_pct / 100, self.config.initial_capital * 0.08 / equity)
                position_value = equity * size_pct
                shares = max(1, int(position_value / fill_price))

                entry_cost = self.cost_model.compute_entry_cost(
                    fill_price, shares, sig.direction, vol.vol_scale
                )
                equity -= entry_cost.total

                open_positions.append(
                    _OpenPosition(
                        ticker=sig.ticker,
                        direction=sig.direction,
                        strategy=sig.strategy,
                        entry_date=dt,
                        entry_price=fill_price,
                        shares=shares,
                        position_size_pct=size_pct,
                        stop_loss=sig.stop_loss,
                        target=sig.target,
                        max_hold_days=sig.max_hold_days,
                        conviction=sig.conviction,
                        signal_score=sig.signal_score,
                    )
                )
                signals = [s for s in signals if s.ticker != sig.ticker]

            dd = (equity - peak_equity) / peak_equity if peak_equity > 0 else 0.0
            equity_curve.append({"date": str(dt), "equity": round(equity, 2), "drawdown_pct": round(dd, 4)})

        # Force-close any positions still open at window end
        last_date = test_dates[-1]
        dt = last_date.date() if hasattr(last_date, "date") else last_date
        for pos in open_positions:
            ticker_df = price_data.get(pos.ticker)
            if ticker_df is None:
                continue
            valid = ticker_df.index[ticker_df.index <= last_date]
            if valid.empty:
                continue
            exit_price = float(ticker_df.loc[valid[-1], "Close"])
            trade = self._close_position(pos, dt, exit_price, "window_end", vol.vol_scale)
            equity += trade.pnl_dollars
            peak_equity = max(peak_equity, equity)
            closed_trades.append(trade)

        return closed_trades, equity, peak_equity

    def _check_exit(
        self, pos: _OpenPosition, bar: pd.Series
    ) -> tuple[float | None, str]:
        """Determine if a position should be exited on this bar."""
        high = float(bar["High"])
        low = float(bar["Low"])
        close = float(bar["Close"])

        if pos.direction == "long":
            if low <= pos.stop_loss:
                return pos.stop_loss, "stop_loss"
            if high >= pos.target:
                return pos.target, "target_hit"
        else:
            if high >= pos.stop_loss:
                return pos.stop_loss, "stop_loss"
            if low <= pos.target:
                return pos.target, "target_hit"

        if pos.bars_held >= pos.max_hold_days:
            return close, "max_hold"

        return None, ""

    def _close_position(
        self,
        pos: _OpenPosition,
        exit_date: date,
        exit_price: float,
        exit_reason: str,
        vol_scale: float,
    ) -> BacktestTrade:
        exit_cost = self.cost_model.compute_exit_cost(
            exit_price,
            pos.shares,
            pos.direction,
            pos.bars_held,
            pos.ticker,
            vol_scale,
        )

        if pos.direction == "long":
            raw_pnl = (exit_price - pos.entry_price) * pos.shares
        else:
            raw_pnl = (pos.entry_price - exit_price) * pos.shares

        net_pnl = raw_pnl - exit_cost.total
        pnl_pct = net_pnl / (pos.entry_price * pos.shares) if pos.entry_price > 0 else 0.0

        return BacktestTrade(
            ticker=pos.ticker,
            direction=pos.direction,
            strategy=pos.strategy,
            entry_date=pos.entry_date,
            entry_price=pos.entry_price,
            exit_date=exit_date,
            exit_price=exit_price,
            shares=pos.shares,
            position_size_pct=pos.position_size_pct,
            pnl_dollars=round(net_pnl, 2),
            pnl_pct=round(pnl_pct, 4),
            hold_days=pos.bars_held,
            exit_reason=exit_reason,
            conviction=pos.conviction,
            signal_score=pos.signal_score,
        )

    @staticmethod
    def _already_in(ticker: str, positions: list[_OpenPosition]) -> bool:
        return any(p.ticker == ticker for p in positions)

    def _compile_result(
        self,
        trades: list[BacktestTrade],
        equity_curve: list[dict],
    ) -> BacktestResult:
        """Aggregate all out-of-sample trades into final BacktestResult."""
        from backtest.statistical_tests import run_validation

        if not trades:
            return BacktestResult(
                strategy=StrategyName(self.strategy.name),
                config=self.config,
                total_return_pct=0.0,
                cagr_pct=0.0,
                sharpe_ratio=0.0,
                sortino_ratio=0.0,
                win_rate=0.0,
                avg_win_pct=0.0,
                avg_loss_pct=0.0,
                profit_factor=0.0,
                max_drawdown_pct=0.0,
                total_trades=0,
                avg_hold_days=0.0,
                equity_curve=equity_curve,
                trades=[],
                monthly_returns=[],
                regime_performance={},
                validation={"passed": False, "reason": "no trades"},
            )

        pnls = [t.pnl_pct for t in trades]
        pnl_dollars = [t.pnl_dollars for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        win_rate = len(wins) / len(pnls) if pnls else 0.0
        avg_win = float(np.mean(wins)) if wins else 0.0
        avg_loss = float(np.mean(losses)) if losses else 0.0
        gross_profit = sum(d for d in pnl_dollars if d > 0)
        gross_loss = abs(sum(d for d in pnl_dollars if d < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        total_return = sum(pnl_dollars)
        total_return_pct = total_return / self.config.initial_capital

        # CAGR from equity curve
        if len(equity_curve) >= 2:
            final_eq = equity_curve[-1]["equity"]
            n_years = len(equity_curve) / 252
            cagr = (final_eq / self.config.initial_capital) ** (1 / max(0.01, n_years)) - 1
        else:
            cagr = 0.0

        # Sharpe & Sortino from trade returns
        pnl_arr = np.array(pnls)
        daily_rf = self.config.risk_free_rate / 252
        excess = pnl_arr - daily_rf
        sharpe = float(np.mean(excess) / np.std(excess) * np.sqrt(252)) if np.std(excess) > 0 else 0.0

        downside = pnl_arr[pnl_arr < 0]
        downside_std = float(np.std(downside)) if len(downside) > 1 else 1.0
        sortino = float(np.mean(excess) / downside_std * np.sqrt(252)) if downside_std > 0 else 0.0

        # Max drawdown from equity curve
        equities = [e["equity"] for e in equity_curve]
        max_dd = 0.0
        peak = equities[0] if equities else self.config.initial_capital
        for eq in equities:
            peak = max(peak, eq)
            dd = (eq - peak) / peak
            max_dd = min(max_dd, dd)

        # Monthly returns
        monthly = self._compute_monthly_returns(trades)

        avg_hold = float(np.mean([t.hold_days for t in trades])) if trades else 0.0

        validation = run_validation(pnls, n_variants=1)

        return BacktestResult(
            strategy=StrategyName(self.strategy.name),
            config=self.config,
            total_return_pct=round(total_return_pct, 4),
            cagr_pct=round(cagr, 4),
            sharpe_ratio=round(sharpe, 3),
            sortino_ratio=round(sortino, 3),
            win_rate=round(win_rate, 4),
            avg_win_pct=round(avg_win, 4),
            avg_loss_pct=round(avg_loss, 4),
            profit_factor=round(min(profit_factor, 99.0), 3),
            max_drawdown_pct=round(max_dd, 4),
            total_trades=len(trades),
            avg_hold_days=round(avg_hold, 1),
            equity_curve=equity_curve,
            trades=trades,
            monthly_returns=monthly,
            regime_performance={},
            validation=validation,
        )

    @staticmethod
    def _compute_monthly_returns(trades: list[BacktestTrade]) -> list[dict]:
        if not trades:
            return []

        monthly: dict[str, float] = {}
        for t in trades:
            key = t.exit_date.strftime("%Y-%m")
            monthly[key] = monthly.get(key, 0.0) + t.pnl_pct

        return [{"month": k, "return_pct": round(v, 4)} for k, v in sorted(monthly.items())]

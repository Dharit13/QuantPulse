"""Portfolio state endpoint — current positions, exposure, risk metrics."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from backend.adaptive.vol_context import compute_vol_context
from backend.data.fetcher import DataFetcher
from backend.models.schemas import PortfolioState, Regime, StrategyName, TradeSignal
from backend.regime.detector import detect_regime
from backend.tracker.trade_journal import TradeJournal

router = APIRouter(prefix="/portfolio", tags=["portfolio"])
logger = logging.getLogger(__name__)
_fetcher = DataFetcher()
_journal = TradeJournal(fetcher=_fetcher)


@router.get("/state", response_model=PortfolioState)
async def get_portfolio_state() -> PortfolioState:
    """Current portfolio state including active trades and risk metrics."""
    vix_df = _fetcher.get_daily_ohlcv("^VIX", period="1y")
    spy_df = _fetcher.get_daily_ohlcv("SPY", period="1y")
    regime_result = detect_regime(vix_df, spy_df)
    regime: Regime = regime_result["regime"]
    confidence = regime_result["confidence"]

    active_entries = _journal.get_active_trades()

    active_signals: list[TradeSignal] = []
    for t in active_entries:
        active_signals.append(
            TradeSignal(
                strategy=t.strategy if isinstance(t.strategy, StrategyName) else StrategyName(t.strategy),
                ticker=t.ticker,
                direction=t.direction,
                conviction=t.signal_score / 100,
                kelly_size_pct=t.kelly_fraction_used * 100,
                entry_price=t.entry_price,
                stop_loss=t.stop_loss,
                target=t.target_1,
                max_hold_days=t.max_hold_days,
                edge_reason="Active position",
                kill_condition="See trade plan",
                expected_sharpe=0.0,
                signal_score=t.signal_score,
            )
        )

    gross = sum(t.position_size_pct for t in active_entries)
    long_exp = sum(t.position_size_pct for t in active_entries if t.direction == "long")
    short_exp = sum(t.position_size_pct for t in active_entries if t.direction == "short")
    net = long_exp - short_exp

    summary = _journal.compute_summary()
    strategy_pnl = {}
    for s in StrategyName:
        strats = [t for t in _journal.get_closed_trades(strategy=s)]
        strategy_pnl[s] = sum(t.pnl_dollars or 0 for t in strats)

    return PortfolioState(
        regime=regime,
        regime_confidence=confidence,
        gross_exposure=round(gross, 4),
        net_exposure=round(net, 4),
        daily_var=0.0,
        current_drawdown_pct=0.0,
        active_trades=active_signals,
        strategy_pnl=strategy_pnl,
        total_pnl_ytd=summary.get("total_pnl_dollars", 0),
        portfolio_sharpe_30d=0.0,
    )


@router.get("/alerts")
async def check_alerts() -> list[dict]:
    """Check active trades for stop/target/time alerts."""
    return _journal.check_active_trade_alerts()

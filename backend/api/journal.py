"""Trade journal endpoints — log, close, and query trades."""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel

from backend.api.envelope import err, ok
from backend.models.schemas import (
    PerformanceStats,
    PhantomTrade,
    StrategyName,
    TradeEntry,
)
from backend.tracker.signal_audit import SignalAuditor
from backend.tracker.strategy_performance import StrategyPerformanceTracker
from backend.tracker.trade_journal import TradeJournal

router = APIRouter(prefix="/journal", tags=["journal"])
logger = logging.getLogger(__name__)
_journal = TradeJournal()
_performance = StrategyPerformanceTracker(journal=_journal)
_auditor = SignalAuditor()


class ExitRequest(BaseModel):
    exit_date: date
    exit_price: float
    exit_reason: str
    exit_notes: str = ""


# ── Trade CRUD ──────────────────────────────────────────────


@router.post("/trades", response_model=dict)
async def log_trade(entry: TradeEntry) -> dict:
    """Log a new trade entry."""
    trade_id = _journal.log_entry(entry)
    return ok({"trade_id": trade_id, "status": "logged"})


@router.post("/trades/{trade_id}/exit", response_model=dict)
async def close_trade(trade_id: int, req: ExitRequest) -> dict:
    """Close an active trade with exit details."""
    result = _journal.log_exit(
        trade_id=trade_id,
        exit_date=req.exit_date,
        exit_price=req.exit_price,
        exit_reason=req.exit_reason,
        exit_notes=req.exit_notes,
    )
    if result is None:
        return err("not_found", f"Trade {trade_id} not found", status=404)
    return ok({
        "trade_id": trade_id,
        "pnl_dollars": result.pnl_dollars,
        "pnl_percent": result.pnl_percent,
        "status": "closed",
    })


@router.get("/trades/active", response_model=list[TradeEntry])
async def get_active_trades():
    """All currently open trades."""
    return ok(_journal.get_active_trades())


@router.get("/trades/closed", response_model=list[TradeEntry])
async def get_closed_trades(
    strategy: StrategyName | None = None,
    since: date | None = None,
) -> list[TradeEntry]:
    return ok(_journal.get_closed_trades(strategy=strategy, since=since))


@router.get("/trades/{trade_id}", response_model=TradeEntry)
async def get_trade(trade_id: int) -> TradeEntry:
    trade = _journal.get_trade(trade_id)
    if trade is None:
        return err("not_found", f"Trade {trade_id} not found", status=404)
    return ok(trade)


# ── Phantom Trades ──────────────────────────────────────────


@router.post("/phantoms", response_model=dict)
async def log_phantom(phantom: PhantomTrade) -> dict:
    """Log a signal the user passed on."""
    pid = _journal.log_phantom(phantom)
    return ok({"phantom_id": pid, "status": "logged"})


@router.get("/phantoms", response_model=list[PhantomTrade])
async def get_phantoms(
    strategy: StrategyName | None = None,
    since: date | None = None,
) -> list[PhantomTrade]:
    return ok(_journal.get_phantom_trades(strategy=strategy, since=since))


# ── Performance ─────────────────────────────────────────────


@router.get("/performance", response_model=PerformanceStats)
async def get_performance(since: date | None = None) -> PerformanceStats:
    """Overall and per-strategy performance stats."""
    return ok(_performance.overall_stats(since=since))


@router.get("/performance/judgment", response_model=dict)
async def judgment_report(since: date | None = None) -> dict:
    """Your judgment vs the model — trades taken vs phantoms."""
    return ok(_performance.judgment_vs_model(since=since))


@router.get("/performance/contribution", response_model=dict)
async def contribution_breakdown(since: date | None = None) -> dict:
    """Each strategy's fractional P&L contribution."""
    return ok(_performance.contribution_breakdown(since=since))


# ── Signal Audit ────────────────────────────────────────────


@router.get("/audit/signals", response_model=list[dict])
async def get_signal_audit(
    strategy: StrategyName | None = None,
    ticker: str | None = None,
    since: date | None = None,
) -> list[dict]:
    return ok(_auditor.get_signals(strategy=strategy, ticker=ticker, since=since))


@router.get("/audit/trade/{trade_id}", response_model=dict)
async def get_trade_audit(trade_id: int) -> dict:
    """Full audit trail for a specific trade."""
    report = _auditor.build_trade_audit(trade_id)
    if report is None:
        return err("not_found", f"Trade {trade_id} not found", status=404)
    return ok(report)


@router.get("/audit/accuracy", response_model=dict)
async def signal_accuracy(
    strategy: StrategyName | None = None,
    since: date | None = None,
) -> dict:
    return ok(_auditor.signal_accuracy_report(strategy=strategy, since=since))

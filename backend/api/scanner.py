"""Universe scanner — generate today's top trade ideas across all strategies.

The scan runs strategies in a background thread to avoid blocking the
async event loop.  Catalyst and cross-asset scans are limited to a
manageable ticker subset so the endpoint responds in <30 seconds.

Every signal generated is automatically logged to the signal audit trail
and created as a phantom trade for shadow-book tracking.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from fastapi import APIRouter, Query

from backend.adaptive.vol_context import VolContext, compute_vol_context
from backend.config import settings
from backend.data.cache import data_cache
from backend.data.fetcher import DataFetcher
from backend.models.schemas import Regime, ScannerResult, StrategyName, TradeSignal
from backend.regime.detector import detect_regime
from backend.tracker.signal_audit import SignalAuditor

router = APIRouter(prefix="/scan", tags=["scanner"])
logger = logging.getLogger(__name__)
_fetcher = DataFetcher()
_executor = ThreadPoolExecutor(max_workers=2)
_auditor = SignalAuditor()

SCAN_WATCHLIST = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
    "JPM", "V", "UNH", "JNJ", "XOM", "PG", "MA", "HD", "COST", "ABBV",
    "CRM", "MRK", "CVX", "LLY", "PEP", "KO", "AVGO", "TMO", "MCD",
    "CSCO", "ACN", "ABT", "DHR", "NKE", "TXN", "WMT", "NEE", "PM",
    "UPS", "RTX", "LOW", "HON", "IBM", "GS", "CAT", "BA", "AMGN",
    "AMD", "INTC", "QCOM", "AMAT", "ADI",
]


def _log_signals_to_shadow_book(signals: list[TradeSignal]) -> None:
    """Auto-log every signal to the audit trail and create phantom entries."""
    from datetime import date as date_type

    from backend.models.schemas import PhantomTrade
    from backend.tracker.trade_journal import TradeJournal

    journal = TradeJournal()
    for sig in signals:
        try:
            _auditor.log_signal(sig, acted_on=False)
            phantom = PhantomTrade(
                ticker=sig.ticker,
                direction=sig.direction,
                strategy=sig.strategy,
                signal_score=sig.signal_score,
                signal_date=date_type.today(),
                entry_price_suggested=sig.entry_price,
                stop_suggested=sig.stop_loss,
                target_suggested=sig.target,
                pass_reason="auto-logged (advisory mode)",
            )
            journal.log_phantom(phantom)
        except Exception:
            logger.debug("Failed to shadow-log signal for %s", sig.ticker)


def _run_scan(vol: VolContext, regime: Regime) -> list[TradeSignal]:
    """Execute all strategy scans synchronously (runs in thread pool)."""
    all_signals: list[TradeSignal] = []

    if settings.enable_catalyst:
        try:
            from backend.strategies.catalyst_event import CatalystEventStrategy
            catalyst = CatalystEventStrategy()
            all_signals.extend(catalyst.generate_signals(vol, tickers=SCAN_WATCHLIST, regime=regime.value))
        except Exception as e:
            logger.warning("Catalyst scan error: %s", e)

    if settings.enable_cross_asset:
        try:
            from backend.strategies.cross_asset_momentum import CrossAssetMomentumStrategy
            cross = CrossAssetMomentumStrategy()
            all_signals.extend(cross.generate_signals(vol, tickers=SCAN_WATCHLIST, regime=regime.value))
        except Exception as e:
            logger.warning("CrossAsset scan error: %s", e)

    if settings.enable_gap_reversion:
        try:
            from backend.strategies.gap_reversion import GapReversionStrategy
            gap = GapReversionStrategy()
            all_signals.extend(gap.generate_signals(vol, tickers=SCAN_WATCHLIST, regime=regime.value))
        except Exception as e:
            logger.warning("GapReversion scan error: %s", e)

    return all_signals


@router.get("/", response_model=ScannerResult)
async def scan_universe(
    max_signals: int = Query(default=10, ge=1, le=50),
    min_score: float = Query(default=60.0, ge=0, le=100),
) -> ScannerResult:
    """Synchronous scan (blocks until done). Use /start-scan + /status for async."""
    vix_df = _fetcher.get_daily_ohlcv("^VIX", period="1y")
    spy_df = _fetcher.get_daily_ohlcv("SPY", period="1y")
    regime_result = detect_regime(vix_df, spy_df)
    regime: Regime = regime_result["regime"]
    vol = compute_vol_context(spy_df, vix_df)

    loop = asyncio.get_event_loop()
    all_signals = await loop.run_in_executor(_executor, _run_scan, vol, regime)

    filtered = [s for s in all_signals if s.signal_score >= min_score]
    filtered.sort(key=lambda s: s.conviction, reverse=True)
    filtered = filtered[:max_signals]

    return ScannerResult(
        timestamp=datetime.utcnow(),
        regime=regime,
        signals=filtered,
        total_signals=len(all_signals),
    )


# ── Background scan state ──

_scanner_state: dict = {
    "status": "idle",
    "progress": 0,
    "total": len(SCAN_WATCHLIST),
    "result": None,
    "error": None,
}


def _run_scanner_background(max_signals: int, min_score: float) -> None:
    """Run the full scan in a background thread, updating _scanner_state."""
    global _scanner_state
    try:
        _scanner_state["status"] = "scanning"
        _scanner_state["error"] = None
        _scanner_state["progress"] = 0
        _scanner_state["total"] = 3  # regime + vol + strategies

        vix_df = _fetcher.get_daily_ohlcv("^VIX", period="1y")
        spy_df = _fetcher.get_daily_ohlcv("SPY", period="1y")
        regime_result = detect_regime(vix_df, spy_df)
        regime: Regime = regime_result["regime"]
        vol = compute_vol_context(spy_df, vix_df)
        _scanner_state["progress"] = 1

        all_signals = _run_scan(vol, regime)
        _scanner_state["progress"] = 2

        # Auto-log all signals to shadow book before filtering
        _log_signals_to_shadow_book(all_signals)

        filtered = [s for s in all_signals if s.signal_score >= min_score]
        filtered.sort(key=lambda s: s.conviction, reverse=True)
        filtered = filtered[:max_signals]
        _scanner_state["progress"] = 3

        result = ScannerResult(
            timestamp=datetime.utcnow(),
            regime=regime,
            signals=filtered,
            total_signals=len(all_signals),
        )
        result_dict = result.model_dump(mode="json")
        _scanner_state["result"] = result_dict
        _scanner_state["status"] = "done"
        data_cache.set("scanner:last_result", result_dict, ttl_hours=24.0)
        logger.info("Background scan done: %d signals (of %d total)", len(filtered), len(all_signals))
    except Exception as e:
        _scanner_state["status"] = "error"
        _scanner_state["error"] = str(e)
        logger.exception("Background scan failed")


@router.post("/start-scan")
async def start_scan(
    max_signals: int = Query(default=10, ge=1, le=50),
    min_score: float = Query(default=60.0, ge=0, le=100),
) -> dict:
    """Kick off a scanner run in the background. Returns immediately."""
    if _scanner_state["status"] == "scanning":
        return {
            "status": "already_scanning",
            "progress": _scanner_state["progress"],
            "total": _scanner_state["total"],
        }

    _scanner_state["status"] = "scanning"
    _scanner_state["progress"] = 0
    _scanner_state["total"] = 3
    _scanner_state["result"] = None

    _executor.submit(_run_scanner_background, max_signals, min_score)
    return {"status": "started"}


@router.get("/status")
async def get_scanner_status() -> dict:
    """Poll scan progress. Returns status, progress, and results when done."""
    result = _scanner_state["result"] if _scanner_state["status"] == "done" else None

    if result is None and _scanner_state["status"] == "idle":
        cached = data_cache.get("scanner:last_result")
        if cached:
            result = cached
            _scanner_state["status"] = "done"
            _scanner_state["result"] = cached

    return {
        "status": _scanner_state["status"],
        "progress": _scanner_state["progress"],
        "total": _scanner_state["total"],
        "result": result,
        "error": _scanner_state["error"],
    }

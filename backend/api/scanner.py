"""Universe scanner — generate today's top trade ideas across all strategies.

Level 8 signal cards: every signal is enriched with tradability proof,
shadow evidence from phantom trades, and strategy health monitoring
before being returned to the user.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date as date_type
from datetime import datetime

from fastapi import APIRouter, Query

from backend.adaptive.vol_context import VolContext, compute_vol_context
from backend.config import settings
from backend.data.cache import data_cache
from backend.data.fetcher import DataFetcher
from backend.models.schemas import (
    EnrichedSignal,
    PhantomTrade,
    Regime,
    ScannerResult,
    ShadowEvidence,
    StrategyHealthSummary,
    StrategyName,
    TradabilityResult,
    TradeSignal,
)
from backend.regime.detector import detect_regime
from backend.signals.tradability import check_tradability
from backend.tracker.shadow_evidence import get_similar_signal_evidence
from backend.tracker.signal_audit import SignalAuditor
from backend.tracker.strategy_health import compute_strategy_health

router = APIRouter(prefix="/scan", tags=["scanner"])
logger = logging.getLogger(__name__)
_fetcher = DataFetcher()
_executor = ThreadPoolExecutor(max_workers=2)
_auditor = SignalAuditor()

def _get_scan_universe() -> list[str]:
    """Build scan universe dynamically from full S&P 500 constituents."""
    try:
        from backend.data.universe import fetch_sp500_constituents
        sp500 = fetch_sp500_constituents()
        if not sp500.empty:
            return sp500["ticker"].tolist()
    except Exception:
        logger.warning("Failed to fetch dynamic universe, using fallback")

    return [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
        "JPM", "V", "UNH", "JNJ", "XOM", "PG", "MA", "HD", "COST", "ABBV",
        "CRM", "MRK", "CVX", "LLY", "PEP", "KO", "AVGO", "TMO", "MCD",
        "CSCO", "ACN", "ABT", "DHR", "NKE", "TXN", "WMT", "NEE", "PM",
        "UPS", "RTX", "LOW", "HON", "IBM", "GS", "CAT", "BA", "AMGN",
        "AMD", "INTC", "QCOM", "AMAT", "ADI",
    ]


# ── Enrichment pipeline ──────────────────────────────────────


def _enrich_signals(
    signals: list[TradeSignal],
    vol: VolContext,
    regime: Regime,
) -> list[EnrichedSignal]:
    """Wrap each TradeSignal with tradability, shadow evidence, and health."""
    enriched: list[EnrichedSignal] = []
    health_cache: dict[str, StrategyHealthSummary] = {}

    for sig in signals:
        try:
            # Tradability gate
            trad = check_tradability(sig, capital=settings.initial_capital)
            trad_result = TradabilityResult(
                passed=trad.passed,
                projected_slippage_bps=trad.projected_slippage_bps,
                pct_adv_used=trad.pct_adv_used,
                borrow_available=trad.borrow_available,
                spread_acceptable=trad.spread_acceptable,
                reasons=trad.reasons,
            )

            # Shadow evidence
            shadow = get_similar_signal_evidence(
                strategy=sig.strategy.value,
                direction=sig.direction,
                regime=regime.value,
                lookback_days=90,
            )
            shadow_result = ShadowEvidence(
                phantom_count=shadow.phantom_count,
                win_rate=shadow.win_rate,
                avg_pnl_pct=shadow.avg_pnl_pct,
                avg_hold_days=shadow.avg_hold_days,
                realized_sharpe=shadow.realized_sharpe,
                best_trade_pct=shadow.best_trade_pct,
                worst_trade_pct=shadow.worst_trade_pct,
                has_enough_data=shadow.has_enough_data,
            )

            # Strategy health (cached per strategy per scan)
            strat_key = sig.strategy.value
            if strat_key not in health_cache:
                health = compute_strategy_health(
                    strategy=strat_key,
                    current_regime=regime.value,
                )
                health_cache[strat_key] = StrategyHealthSummary(
                    status=health.status,
                    rolling_sharpe_60d=health.rolling_sharpe_60d,
                    rolling_win_rate_60d=health.rolling_win_rate_60d,
                    phantom_count_60d=health.phantom_count_60d,
                    slippage_deteriorating=health.slippage_deteriorating,
                    regime_alignment=health.regime_alignment,
                    size_adjustment=health.size_adjustment,
                )
            health_summary = health_cache[strat_key]

            # Final recommendation
            if not trad.passed or health_summary.status == "paused":
                recommendation = "do_not_trade"
                size_reason = "Tradability failed" if not trad.passed else "Strategy paused"
            elif not shadow.has_enough_data or health_summary.status == "degraded":
                recommendation = "conditional_trade"
                size_reason = (
                    "Insufficient shadow data" if not shadow.has_enough_data
                    else "Strategy degraded — reduced size"
                )
            else:
                recommendation = "trade"
                size_reason = "All checks passed"

            size_mode = settings.sizing_mode
            if health_summary.size_adjustment < 1.0:
                size_mode += f"_reduced_{int(health_summary.size_adjustment * 100)}pct"

            enriched.append(EnrichedSignal(
                signal=sig,
                tradability=trad_result,
                shadow_evidence=shadow_result,
                strategy_health=health_summary,
                regime=regime.value,
                regime_alignment=health_summary.regime_alignment,
                recommended_size_mode=size_mode,
                size_adjustment_reason=size_reason,
                final_recommendation=recommendation,
            ))
        except Exception:
            logger.debug("Failed to enrich signal for %s", sig.ticker)

    return enriched


# ── Shadow book logging ──────────────────────────────────────


def _log_signals_to_shadow_book(
    signals: list[TradeSignal],
    regime: Regime,
    vol: VolContext,
) -> None:
    """Auto-log every signal with full context for similarity queries."""
    from backend.tracker.trade_journal import TradeJournal

    journal = TradeJournal()
    for sig in signals:
        try:
            signal_id = _auditor.log_signal(
                sig,
                acted_on=False,
                regime=regime.value,
                vix=vol.vix_current,
            )
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
                regime=regime.value,
                vix_at_signal=vol.vix_current,
                atr_at_signal=vol.spy_atr_pct * 100,
                conviction=sig.conviction,
                signal_id=signal_id,
            )
            journal.log_phantom(phantom)
        except Exception:
            logger.debug("Failed to shadow-log signal for %s", sig.ticker)


# ── Strategy scan ────────────────────────────────────────────


def _run_scan(
    vol: VolContext,
    regime: Regime,
    progress_cb: callable | None = None,
) -> list[TradeSignal]:
    """Execute all strategy scans. Catalyst strategy (the heaviest) gets the
    progress callback and handles its own internal parallelism for insider
    buying. Other strategies run after it completes.
    """
    tickers = _get_scan_universe()
    total_tickers = len(tickers)
    all_signals: list[TradeSignal] = []

    if settings.enable_catalyst:
        try:
            from backend.strategies.catalyst_event import CatalystEventStrategy
            strat = CatalystEventStrategy()
            all_signals.extend(strat.generate_signals(
                vol, tickers=tickers, regime=regime.value,
                progress_cb=progress_cb, progress_total=total_tickers,
            ))
        except Exception as e:
            logger.warning("Catalyst scan error: %s", e)

    if settings.enable_cross_asset:
        try:
            from backend.strategies.cross_asset_momentum import CrossAssetMomentumStrategy
            all_signals.extend(CrossAssetMomentumStrategy().generate_signals(
                vol, tickers=tickers, regime=regime.value,
            ))
        except Exception as e:
            logger.warning("CrossAsset scan error: %s", e)

    if settings.enable_gap_reversion:
        try:
            from backend.strategies.gap_reversion import GapReversionStrategy
            all_signals.extend(GapReversionStrategy().generate_signals(
                vol, tickers=tickers, regime=regime.value,
            ))
        except Exception as e:
            logger.warning("GapReversion scan error: %s", e)

    return all_signals


# ── Endpoints ────────────────────────────────────────────────


@router.get("/")
async def scan_universe(
    max_signals: int = Query(default=10, ge=1, le=50),
    min_score: float = Query(default=60.0, ge=0, le=100),
    refresh: bool = Query(False, description="Force live scan, bypass pipeline cache"),
) -> dict:
    """Returns scanner results from pipeline cache (instant) or live."""
    if not refresh:
        cached = data_cache.get("pipeline:scanner")
        if cached and isinstance(cached, dict):
            return cached

    from backend.pipeline import refresh_scanner
    result = refresh_scanner()
    if result:
        return result

    vix_df = _fetcher.get_daily_ohlcv("^VIX", period="1y", live=True)
    spy_df = _fetcher.get_daily_ohlcv("SPY", period="1y", live=True)
    regime_result = detect_regime(vix_df, spy_df)
    regime: Regime = regime_result["regime"]
    vol = compute_vol_context(spy_df, vix_df)

    loop = asyncio.get_event_loop()
    all_signals = await loop.run_in_executor(_executor, _run_scan, vol, regime)

    enriched = _enrich_signals(all_signals, vol, regime)
    filtered = [e for e in enriched if e.signal.signal_score >= min_score]
    filtered.sort(key=lambda e: e.signal.conviction, reverse=True)
    filtered = filtered[:max_signals]

    result_obj = ScannerResult(
        timestamp=datetime.utcnow(),
        regime=regime,
        signals=filtered,
        total_signals=len(all_signals),
    )
    return {
        "data": result_obj.model_dump(mode="json"),
        "refreshed_at": datetime.utcnow().isoformat(),
    }


# ── Background scan ──────────────────────────────────────────

_scanner_state: dict = {
    "status": "idle",
    "progress": 0,
    "total": 0,
    "universe_size": 0,
    "result": None,
    "result_timestamp": None,
    "error": None,
}


def _run_scanner_background(max_signals: int, min_score: float) -> None:
    """Run the full scan in a background thread, updating _scanner_state."""
    global _scanner_state
    try:
        _scanner_state["status"] = "scanning"
        _scanner_state["error"] = None
        _scanner_state["progress"] = 0
        _scanner_state["total"] = 100
        _scanner_state["step"] = "Detecting market regime..."

        universe = _get_scan_universe()
        _scanner_state["universe_size"] = len(universe)
        _scanner_state["total"] = len(universe)

        vix_df = _fetcher.get_daily_ohlcv("^VIX", period="1y", live=True)
        spy_df = _fetcher.get_daily_ohlcv("SPY", period="1y", live=True)
        regime_result = detect_regime(vix_df, spy_df)
        regime: Regime = regime_result["regime"]
        vol = compute_vol_context(spy_df, vix_df)

        def _on_progress(done: int, total: int, step: str = "") -> None:
            _scanner_state["progress"] = done
            _scanner_state["total"] = total
            if step:
                _scanner_state["step"] = step

        _on_progress(5, len(universe), "Scanning stocks for signals...")

        all_signals = _run_scan(vol, regime, progress_cb=_on_progress)

        _on_progress(len(universe) - 10, len(universe), "Enriching and ranking signals...")
        _log_signals_to_shadow_book(all_signals, regime, vol)

        enriched = _enrich_signals(all_signals, vol, regime)

        filtered = [e for e in enriched if e.signal.signal_score >= min_score]
        filtered.sort(key=lambda e: e.signal.conviction, reverse=True)
        filtered = filtered[:max_signals]

        _on_progress(len(universe), len(universe), "Done")

        result = ScannerResult(
            timestamp=datetime.utcnow(),
            regime=regime,
            signals=filtered,
            total_signals=len(all_signals),
        )
        result_dict = result.model_dump(mode="json")
        _scanner_state["result"] = result_dict
        _scanner_state["result_timestamp"] = datetime.utcnow().isoformat()
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
    _scanner_state["total"] = 4
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
            if not _scanner_state.get("result_timestamp"):
                _scanner_state["result_timestamp"] = (
                    cached.get("timestamp") if isinstance(cached, dict) else None
                )

    return {
        "status": _scanner_state["status"],
        "progress": _scanner_state["progress"],
        "total": _scanner_state["total"],
        "step": _scanner_state.get("step", ""),
        "universe_size": _scanner_state.get("universe_size", 0),
        "result": result,
        "result_timestamp": _scanner_state.get("result_timestamp"),
        "error": _scanner_state["error"],
    }

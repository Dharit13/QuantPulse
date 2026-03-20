"""Universe scanner — generate today's top trade ideas across all strategies.

Level 8 signal cards: every signal is enriched with tradability proof,
shadow evidence from phantom trades, and strategy health monitoring
before being returned to the user.

AI analysis is generated server-side as part of the scan pipeline so
the frontend receives complete results in a single SSE stream.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import UTC, datetime
from datetime import date as date_type

import pandas as pd
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from backend.adaptive.vol_context import VolContext, compute_vol_context
from backend.ai.market_ai import ai_scan_summary, ai_signal_explain
from backend.config import settings
from backend.data.cache import data_cache
from backend.data.fetcher import DataFetcher
from backend.data.sentiment_cache import sentiment_cache
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
        "AAPL",
        "MSFT",
        "GOOGL",
        "AMZN",
        "NVDA",
        "META",
        "TSLA",
        "BRK-B",
        "JPM",
        "V",
        "UNH",
        "JNJ",
        "XOM",
        "PG",
        "MA",
        "HD",
        "COST",
        "ABBV",
        "CRM",
        "MRK",
        "CVX",
        "LLY",
        "PEP",
        "KO",
        "AVGO",
        "TMO",
        "MCD",
        "CSCO",
        "ACN",
        "ABT",
        "DHR",
        "NKE",
        "TXN",
        "WMT",
        "NEE",
        "PM",
        "UPS",
        "RTX",
        "LOW",
        "HON",
        "IBM",
        "GS",
        "CAT",
        "BA",
        "AMGN",
        "AMD",
        "INTC",
        "QCOM",
        "AMAT",
        "ADI",
    ]


# ── Enrichment pipeline ──────────────────────────────────────


def _enrich_signals(
    signals: list[TradeSignal],
    vol: VolContext,
    regime: Regime,
    progress_cb: Callable | None = None,
) -> list[EnrichedSignal]:
    """Wrap each TradeSignal with tradability, shadow evidence, and health."""
    enriched: list[EnrichedSignal] = []
    health_cache: dict[str, StrategyHealthSummary] = {}
    total = len(signals)

    for i, sig in enumerate(signals):
        if progress_cb:
            progress_cb(i, total, sig.ticker)
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

            # Shadow evidence sizing factor
            shadow_size_factor = 1.0
            if shadow.has_enough_data:
                if shadow.win_rate < 0.40:
                    shadow_size_factor = 0.5
                elif shadow.realized_sharpe < 0.5:
                    shadow_size_factor = 0.7
                elif shadow.win_rate > 0.60 and shadow.realized_sharpe > 1.0:
                    shadow_size_factor = 1.0  # full Kelly allowed

            # Final recommendation
            if not trad.passed or health_summary.status == "paused":
                recommendation = "do_not_trade"
                size_reason = "Tradability failed" if not trad.passed else "Strategy paused"
            elif not shadow.has_enough_data or health_summary.status == "degraded":
                recommendation = "conditional_trade"
                size_reason = (
                    "Insufficient shadow data" if not shadow.has_enough_data else "Strategy degraded — reduced size"
                )
            else:
                recommendation = "trade"
                size_reason = "All checks passed"

            size_mode = settings.sizing_mode
            if health_summary.size_adjustment < 1.0:
                size_mode += f"_reduced_{int(health_summary.size_adjustment * 100)}pct"

            enriched.append(
                EnrichedSignal(
                    signal=sig,
                    tradability=trad_result,
                    shadow_evidence=shadow_result,
                    strategy_health=health_summary,
                    regime=regime.value,
                    regime_alignment=health_summary.regime_alignment,
                    recommended_size_mode=size_mode,
                    size_adjustment_reason=size_reason,
                    final_recommendation=recommendation,
                    shadow_size_factor=shadow_size_factor,
                )
            )
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


# ── Sentiment-driven signal generation ────────────────────────


def _generate_sentiment_signals(
    existing_tickers: set[str],
    vol: VolContext,
    max_signals: int = 5,
) -> list[TradeSignal]:
    """Generate signals from sentiment cache for tickers with strong FinBERT
    scores and momentum confirmation. Only picks tickers not already covered
    by the 5 core strategies.

    All thresholds are adaptive:
    - Sentiment thresholds tighten in high vol (need stronger signal through noise)
    - Stop/target widths scale with vol_scale
    - Position sizing inversely proportional to vol via position_scale
    - Hold period adjusts to market speed via speed_scale
    """
    cached_tickers = sentiment_cache.all_tickers()
    if not cached_tickers:
        return []

    # In high vol, require more extreme sentiment to cut through noise
    vol_adjust = min(10.0, max(-5.0, (vol.vol_scale - 1.0) * 8.0))
    bullish_min = 72.0 + vol_adjust
    bearish_max = 28.0 - vol_adjust

    candidates: list[tuple[str, float, str]] = []
    for ticker in cached_tickers:
        if ticker in existing_tickers:
            continue
        entry = sentiment_cache.get(ticker)
        if entry is None:
            continue
        if entry.composite_score > bullish_min:
            candidates.append((ticker, entry.composite_score, "bullish"))
        elif entry.composite_score < bearish_max:
            candidates.append((ticker, entry.composite_score, "bearish"))

    if not candidates:
        return []

    candidates.sort(key=lambda x: abs(x[1] - 50), reverse=True)
    candidates = candidates[: max_signals * 2]

    # Momentum rejection threshold scales with market speed
    momentum_floor = -3.0 * max(0.5, vol.speed_scale)

    # Stop/target ATR multipliers widen in high vol
    stop_atr_mult = 1.5 + vol.vol_scale * 0.5
    target_atr_mult = 2.0 + vol.vol_scale * 1.0

    # Hold period shortens in fast markets
    hold_days = max(10, int(30 / max(0.5, vol.speed_scale)))

    signals: list[TradeSignal] = []
    for ticker, score, label in candidates:
        if len(signals) >= max_signals:
            break
        try:
            df = _fetcher.get_daily_ohlcv(ticker, period="3mo", live=False)
            if df.empty or len(df) < 20:
                continue
            close = df["Close"]
            price = float(close.iloc[-1])
            ret_5d = float((close.iloc[-1] / close.iloc[-5] - 1) * 100) if len(close) >= 5 else 0.0

            high = df["High"]
            low = df["Low"]
            prev_close = close.shift(1)
            tr = pd.concat(
                [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
                axis=1,
            ).max(axis=1)
            atr = float(tr.tail(14).mean())

            # Reject signals where momentum contradicts sentiment
            if label == "bullish" and ret_5d < momentum_floor:
                continue
            if label == "bearish" and ret_5d > abs(momentum_floor):
                continue

            direction = "long" if label == "bullish" else "short"

            # Conviction derived from sentiment extremity (how far from 50)
            sentiment_extremity = abs(score - 50) / 50.0  # 0.0 – 1.0
            conviction = min(0.85, 0.35 + sentiment_extremity * 0.5)

            if direction == "long":
                stop = round(price - atr * stop_atr_mult, 2)
                target = round(price + atr * target_atr_mult, 2)
            else:
                stop = round(price + atr * stop_atr_mult, 2)
                target = round(price - atr * target_atr_mult, 2)

            # Signal score from sentiment extremity + momentum alignment
            signal_score = 50.0 + sentiment_extremity * 30.0 + min(15.0, abs(ret_5d) * 1.5)

            # Kelly sizing scales inversely with vol
            kelly_pct = conviction * vol.position_scale * 4.0

            signals.append(
                TradeSignal(
                    strategy=StrategyName.CATALYST,
                    ticker=ticker,
                    direction=direction,
                    conviction=round(conviction, 3),
                    kelly_size_pct=round(kelly_pct, 2),
                    entry_price=round(price, 2),
                    stop_loss=stop,
                    target=target,
                    max_hold_days=hold_days,
                    edge_reason=(
                        f"FinBERT sentiment strongly {label} ({score:.0f}/100) "
                        f"with {ret_5d:+.1f}% 5d momentum confirmation"
                    ),
                    kill_condition=f"Sentiment reversal or stop at ${stop:.2f}",
                    expected_sharpe=round(1.0 + sentiment_extremity * 0.5, 2),
                    signal_score=round(min(95.0, signal_score), 1),
                )
            )
        except Exception:
            logger.debug("Sentiment signal generation failed for %s", ticker)

    return signals


# ── Strategy scan ────────────────────────────────────────────


def _run_catalyst(
    vol: VolContext,
    tickers: list[str],
    regime_value: str,
    progress_cb: Callable | None,
    progress_total: int,
) -> list[TradeSignal]:
    from backend.strategies.catalyst_event import CatalystEventStrategy

    return CatalystEventStrategy().generate_signals(
        vol,
        tickers=tickers,
        regime=regime_value,
        progress_cb=progress_cb,
        progress_total=progress_total,
    )


def _run_cross_asset(vol: VolContext, tickers: list[str], regime_value: str) -> list[TradeSignal]:
    from backend.strategies.cross_asset_momentum import CrossAssetMomentumStrategy

    return CrossAssetMomentumStrategy().generate_signals(vol, tickers=tickers, regime=regime_value)


def _run_stat_arb(vol: VolContext, tickers: list[str], regime_value: str) -> list[TradeSignal]:
    from backend.strategies.stat_arb import StatArbStrategy

    strat = StatArbStrategy()
    cached_raw = data_cache.get("stat_arb:pairs")
    if isinstance(cached_raw, list):
        strat.active_pairs = [dict(p) for p in cached_raw if isinstance(p, dict)]
    else:
        logger.info("StatArb: no cached pairs, running find_pairs()")
        strat.find_pairs(vol)
        if strat.active_pairs:
            data_cache.set("stat_arb:pairs", strat.active_pairs, ttl_hours=24.0)
    return strat.generate_signals(vol, tickers=tickers, regime=regime_value)


def _run_flow(vol: VolContext, tickers: list[str], regime_value: str) -> list[TradeSignal]:
    from backend.strategies.flow_imbalance import FlowImbalanceStrategy

    return FlowImbalanceStrategy().generate_signals(vol, tickers=tickers, regime=regime_value)


def _run_gap_reversion(vol: VolContext, tickers: list[str], regime_value: str) -> list[TradeSignal]:
    from backend.strategies.gap_reversion import GapReversionStrategy

    premarket: dict[str, float] = {}
    if settings.enable_polygon:
        try:
            from backend.data.sources.polygon_src import polygon_source

            premarket = polygon_source.get_premarket_prices(tickers)
            if premarket:
                logger.info("Gap reversion: fetched %d premarket prices from Polygon", len(premarket))
        except Exception:
            logger.debug("Polygon premarket fetch failed, using regular prices")

    return GapReversionStrategy().generate_signals(
        vol, tickers=tickers, regime=regime_value, premarket_prices=premarket
    )


def _run_scan(
    vol: VolContext,
    regime: Regime,
    progress_cb: Callable | None = None,
) -> list[TradeSignal]:
    """Execute all strategy scans in parallel using ThreadPoolExecutor.

    Each strategy is independent — they share inputs (tickers, vol, regime)
    but produce independent TradeSignal lists. Running concurrently cuts
    scan time from sum(all strategies) to max(slowest strategy).
    """
    tickers = _get_scan_universe()
    total_tickers = len(tickers)
    all_signals: list[TradeSignal] = []
    strategies_run: list[str] = []

    strategy_timeout = 600

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures: dict[str, object] = {}

        if settings.enable_catalyst:
            futures["catalyst"] = pool.submit(_run_catalyst, vol, tickers, regime.value, progress_cb, total_tickers)
        if settings.enable_cross_asset:
            futures["cross_asset"] = pool.submit(_run_cross_asset, vol, tickers, regime.value)
        if settings.enable_stat_arb:
            futures["stat_arb"] = pool.submit(_run_stat_arb, vol, tickers, regime.value)
        if settings.enable_flow:
            futures["flow"] = pool.submit(_run_flow, vol, tickers, regime.value)
        if settings.enable_gap_reversion:
            futures["gap_reversion"] = pool.submit(_run_gap_reversion, vol, tickers, regime.value)

        for name, future in futures.items():
            try:
                sigs = future.result(timeout=strategy_timeout)
                all_signals.extend(sigs)
                strategies_run.append(f"{name}({len(sigs)})")
            except TimeoutError:
                logger.warning("%s scan timed out after %ds", name, strategy_timeout)
            except Exception as e:
                logger.warning("%s scan error: %s", name, e)

    # Sentiment-driven signals for tickers not already covered by strategies
    try:
        existing = {s.ticker for s in all_signals}
        sent_sigs = _generate_sentiment_signals(existing, vol)
        if sent_sigs:
            all_signals.extend(sent_sigs)
            strategies_run.append(f"sentiment({len(sent_sigs)})")
    except Exception as e:
        logger.warning("Sentiment signal generation error: %s", e)

    logger.info(
        "Scanner ran %d strategies: %s → %d total signals",
        len(strategies_run),
        ", ".join(strategies_run) or "none",
        len(all_signals),
    )
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

    vix_df = _fetcher.get_daily_ohlcv("^VIX", period="1y", live=False)
    spy_df = _fetcher.get_daily_ohlcv("SPY", period="1y", live=False)
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
        timestamp=datetime.now(UTC),
        regime=regime,
        signals=filtered,
        total_signals=len(all_signals),
    )
    return {
        "data": result_obj.model_dump(mode="json"),
        "refreshed_at": datetime.now(UTC).isoformat(),
    }


# ── Background scan ──────────────────────────────────────────

_scanner_state: dict = {
    "status": "idle",
    "progress": 0,
    "total": 0,
    "universe_size": 0,
    "result": None,
    "result_timestamp": None,
    "ai_summary": None,
    "signal_explanations": None,
    "error": None,
}


def _run_scanner_background(max_signals: int, min_score: float) -> None:
    """Run the full scan in a background thread, updating _scanner_state."""
    from concurrent.futures import ThreadPoolExecutor as _Pool

    from backend.progress import ScanProgressTracker

    global _scanner_state
    try:
        _scanner_state["status"] = "scanning"
        _scanner_state["error"] = None

        tracker = ScanProgressTracker.create(
            [
                ("regime", 5),
                ("scan", 180),
                ("enrich", 60),
                ("filter", 2),
                ("ai_summary", 15),
                ("ai_explain", 15),
            ],
            _scanner_state,
            "progress:scanner",
        )

        tracker.start_phase("regime", "Detecting market regime...")

        universe = _get_scan_universe()
        _scanner_state["universe_size"] = len(universe)

        vix_df = _fetcher.get_daily_ohlcv("^VIX", period="1y", live=False)
        spy_df = _fetcher.get_daily_ohlcv("SPY", period="1y", live=False)
        regime_result = detect_regime(vix_df, spy_df)
        regime: Regime = regime_result["regime"]
        vol = compute_vol_context(spy_df, vix_df)

        tracker.start_phase("scan", "AI selecting stocks to scan...")

        scan_timeout_sec = 600

        def _on_scan_progress(d: int, t: int, step: str = "") -> None:
            if step:
                tracker.update_within_phase(d, t, step)

        with ThreadPoolExecutor(max_workers=1) as scan_pool:
            scan_future = scan_pool.submit(_run_scan, vol, regime, _on_scan_progress)
            try:
                all_signals = scan_future.result(timeout=scan_timeout_sec)
            except TimeoutError:
                logger.warning("Scanner _run_scan timed out after %ds, using partial results", scan_timeout_sec)
                scan_pool.shutdown(wait=False, cancel_futures=True)
                all_signals = []
            except Exception as e:
                logger.warning("Scanner _run_scan failed: %s", e)
                all_signals = []

        n_signals = len(all_signals)
        tracker.start_phase("enrich", f"Found {n_signals} signals, enriching...")

        def _on_enrich_progress(i: int, total: int, ticker: str) -> None:
            tracker.update_within_phase(i, total, f"Enriching signal {i + 1}/{total} ({ticker})")

        with _Pool(max_workers=1) as shadow_pool:
            shadow_future = shadow_pool.submit(
                _log_signals_to_shadow_book,
                all_signals,
                regime,
                vol,
            )
            enriched = _enrich_signals(all_signals, vol, regime, progress_cb=_on_enrich_progress)
            try:
                shadow_future.result(timeout=60)
            except (TimeoutError, Exception):
                logger.warning("Shadow book logging timed out or failed")

        tracker.start_phase("filter", "Ranking and filtering...")

        filtered = [e for e in enriched if e.signal.signal_score >= min_score]
        filtered.sort(key=lambda e: e.signal.conviction, reverse=True)
        filtered = filtered[:max_signals]

        result = ScannerResult(
            timestamp=datetime.now(UTC),
            regime=regime,
            signals=filtered,
            total_signals=len(all_signals),
        )
        result_dict = result.model_dump(mode="json")

        tracker.start_phase("ai_summary", "AI analyzing signals...")
        ai_summary = None
        signal_explanations = None
        try:
            from backend.data.ticker_intelligence import format_sentiment_block, get_universe_sentiment

            univ_sentiment = get_universe_sentiment()
            sentiment_block = format_sentiment_block(univ_sentiment)
        except Exception:
            sentiment_block = ""
            logger.debug("Universe sentiment unavailable for AI summary")
        try:
            ai_summary = ai_scan_summary(regime.value, result_dict.get("signals", []), sentiment_block=sentiment_block)
            tracker.start_phase("ai_explain", "AI explaining signals...")
            signal_explanations = ai_signal_explain(result_dict.get("signals", []), sentiment_block=sentiment_block)
        except Exception as e:
            logger.warning("AI analysis failed (scan continues): %s", e)

        tracker.finish()
        tracker.save_history("progress:scanner")

        _scanner_state["result"] = result_dict
        _scanner_state["result_timestamp"] = datetime.now(UTC).isoformat()
        _scanner_state["ai_summary"] = ai_summary
        _scanner_state["signal_explanations"] = signal_explanations
        _scanner_state["status"] = "done"
        data_cache.set("scanner:last_result", result_dict, ttl_hours=24.0)
        data_cache.set("scanner:ai_summary", ai_summary, ttl_hours=24.0)
        data_cache.set("scanner:signal_explanations", signal_explanations, ttl_hours=24.0)
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
    _scanner_state["ai_summary"] = None
    _scanner_state["signal_explanations"] = None

    _executor.submit(_run_scanner_background, max_signals, min_score)
    return {"status": "started"}


@router.get("/status")
async def get_scanner_status() -> dict:
    """Poll scan progress. Returns status, progress, and results when done."""
    status = _scanner_state["status"]
    result = _scanner_state["result"] if status == "done" else None
    ai_summary = _scanner_state.get("ai_summary")
    signal_explanations = _scanner_state.get("signal_explanations")
    result_timestamp = _scanner_state.get("result_timestamp")
    cached_at: str | None = None

    if result is None and status == "idle":
        cached = data_cache.get("scanner:last_result")
        if cached:
            result = cached
            ai_summary = data_cache.get("scanner:ai_summary")
            signal_explanations = data_cache.get("scanner:signal_explanations")
            cached_at = cached.get("timestamp") if isinstance(cached, dict) else None
            result_timestamp = result_timestamp or cached_at

    return {
        "status": status,
        "progress": _scanner_state["progress"],
        "total": _scanner_state["total"],
        "step": _scanner_state.get("step", ""),
        "universe_size": _scanner_state.get("universe_size", 0),
        "result": result,
        "result_timestamp": result_timestamp,
        "cached_at": cached_at,
        "ai_summary": ai_summary,
        "signal_explanations": signal_explanations,
        "error": _scanner_state["error"],
    }


@router.get("/stream")
async def stream_scan():
    """SSE endpoint — streams scan progress in real-time, then the full
    result (including AI analysis) as a single terminal event."""

    async def _event_stream():
        prev_snapshot = ""
        while True:
            snap = {
                "status": _scanner_state["status"],
                "progress": _scanner_state["progress"],
                "total": _scanner_state["total"],
                "step": _scanner_state.get("step", ""),
                "universe_size": _scanner_state.get("universe_size", 0),
                "error": _scanner_state["error"],
            }
            encoded = json.dumps(snap, default=str)

            if _scanner_state["status"] == "done":
                snap["result"] = _scanner_state["result"]
                snap["result_timestamp"] = _scanner_state.get("result_timestamp")
                snap["ai_summary"] = _scanner_state.get("ai_summary")
                snap["signal_explanations"] = _scanner_state.get("signal_explanations")
                yield f"data: {json.dumps(snap, default=str)}\n\n"
                return

            if _scanner_state["status"] == "error":
                yield f"data: {encoded}\n\n"
                return

            if _scanner_state["status"] == "idle":
                cached = data_cache.get("scanner:last_result")
                if cached:
                    snap["status"] = "done"
                    snap["result"] = cached
                    snap["result_timestamp"] = _scanner_state.get("result_timestamp")
                    snap["ai_summary"] = data_cache.get("scanner:ai_summary")
                    snap["signal_explanations"] = data_cache.get("scanner:signal_explanations")
                    yield f"data: {json.dumps(snap, default=str)}\n\n"
                    return
                yield f"data: {encoded}\n\n"
                return

            if encoded != prev_snapshot:
                yield f"data: {encoded}\n\n"
                prev_snapshot = encoded
            else:
                yield ": keepalive\n\n"

            await asyncio.sleep(0.5)

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

"""AI Overnight Swing Scanner — pure Claude reasoning over raw market data.

v2 improvements:
  - Accepts optional current_positions to avoid doubled exposure
  - Feeds recent pick history for performance memory
  - Logs every scan result for outcome tracking
  - Cost tracking on every Claude call

Endpoints:
  POST /overnight/start-scan  — kick off a background scan
  GET  /overnight/status      — poll progress + results
  GET  /overnight/stream      — SSE real-time progress stream
  GET  /overnight/history     — recent scan results + cost log
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from enum import StrEnum

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from backend.ai.market_ai import ai_overnight_analysis
from backend.api.envelope import ok
from backend.data.cache import data_cache
from backend.data.sources.overnight_src import (
    DEFAULT_CRYPTO,
    DEFAULT_STOCKS,
    assemble_crypto_data,
    assemble_macro_data,
    assemble_stock_data,
    check_morning_outcomes,
    compute_scorecard,
    get_recent_outcomes,
    log_scan_result,
)

router = APIRouter(prefix="/overnight", tags=["overnight"])
logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=2)
_scan_lock = threading.Lock()


class ScanMode(StrEnum):
    both = "both"
    stocks = "stocks"
    crypto = "crypto"


_scan_state: dict = {
    "status": "idle",
    "progress": 0,
    "total": 0,
    "step": "",
    "result": None,
    "result_timestamp": None,
    "started_at": None,
    "error": None,
}

_CACHE_KEY = "overnight:last_result"
_CACHE_TTL_HOURS = 4.0


def _is_weekend() -> bool:
    """Check if US stock markets are closed (Saturday=5, Sunday=6)."""
    return datetime.now().weekday() >= 5


def _inject_entry_prices(analysis: dict, stock_data: dict, crypto_data: dict) -> None:
    """Stamp each BUY pick with the actual entry_price from the data we sent Claude."""
    for pick in analysis.get("stock_picks", []):
        if pick.get("action") != "BUY":
            continue
        sym = pick.get("symbol", "")
        sd = stock_data.get(sym, {})
        price = sd.get("indicators", {}).get("price")
        if price:
            pick["entry_price"] = price

    pairs = crypto_data.get("pairs", {})
    for pick in analysis.get("crypto_picks", []):
        if pick.get("action") != "BUY":
            continue
        sym = pick.get("symbol", "")
        cd = pairs.get(sym, {})
        price = cd.get("indicators", {}).get("price")
        if price:
            pick["entry_price"] = price


def _run_scan_background(
    mode: str,
    stock_symbols: list[str],
    crypto_pairs: list[str],
    current_positions: list[str],
) -> None:
    """Run the full overnight scan in a background thread."""
    global _scan_state
    try:
        _scan_state["status"] = "scanning"
        _scan_state["started_at"] = datetime.now(UTC).isoformat()
        _scan_state["error"] = None
        _scan_state["progress"] = 0

        # Weekend context: stock markets are closed Sat/Sun but we still
        # scan stocks for Monday planning
        market_closed_note: str | None = None
        if _is_weekend() and mode in ("both", "stocks"):
            market_closed_note = (
                "Stock markets are closed (weekend). "
                "Stock picks are for Monday: buy at Monday's close (~3:50 PM ET), "
                "sell at Tuesday's open (~9:31 AM ET). "
                "Crypto picks are live now."
            )
            logger.info("Weekend scan: stock picks will be framed for Monday")

        scan_stocks = mode in ("both", "stocks")
        scan_crypto = mode in ("both", "crypto")

        steps = []
        if scan_stocks:
            steps.append("stocks")
        if scan_crypto:
            steps.append("crypto")
        steps += ["macro", "ai_analysis"]
        total_steps = len(steps)
        step_idx = 0

        def _advance(label: str) -> None:
            nonlocal step_idx
            step_idx += 1
            _scan_state["step"] = label
            _scan_state["progress"] = step_idx
            _scan_state["total"] = total_steps

        # 1. Fetch stock data (parallel, pre-filtered, with TA indicators)
        stock_data: dict = {}
        if scan_stocks:
            _scan_state["step"] = f"Fetching + filtering stocks ({len(stock_symbols)} base tickers)..."
            _scan_state["total"] = total_steps
            stock_data = assemble_stock_data(stock_symbols)
            passed = len([k for k in stock_data if not k.startswith("_")])
            _advance(f"Stock data: {passed} tickers passed pre-filter")

        # 2. Fetch crypto data (parallel, pre-filtered)
        crypto_data: dict = {}
        if scan_crypto:
            _scan_state["step"] = f"Fetching + filtering crypto ({len(crypto_pairs)} base pairs)..."
            crypto_data = assemble_crypto_data(crypto_pairs)
            _advance(f"Crypto data: {len(crypto_data.get('pairs', {}))} pairs passed pre-filter")

        # 3. Fetch macro data (cached daily)
        _scan_state["step"] = "Fetching FRED macro data..."
        macro_data = assemble_macro_data()
        _advance(f"Macro data: {len(macro_data)} indicators")

        # 4. Get recent outcomes for performance memory (now a formatted string)
        performance_summary = get_recent_outcomes(days=7)

        # 5. Send to Claude (with positions, history, computed indicators)
        _scan_state["step"] = "Claude AI analyzing pre-filtered data..."
        analysis = ai_overnight_analysis(
            stock_data,
            crypto_data,
            macro_data,
            current_positions=current_positions or None,
            performance_summary=performance_summary,
        )
        _advance("AI analysis complete")

        if analysis is None:
            _scan_state["status"] = "error"
            _scan_state["error"] = "AI analysis returned no results — check ANTHROPIC_API_KEY"
            return

        if market_closed_note:
            analysis["market_closed_note"] = market_closed_note

        # 6. Inject entry prices from the data we sent Claude, then log
        _inject_entry_prices(analysis, stock_data, crypto_data)
        log_scan_result(analysis)

        _scan_state["result"] = analysis
        _scan_state["result_timestamp"] = datetime.now(UTC).isoformat()
        _scan_state["status"] = "done"
        data_cache.set(
            _CACHE_KEY,
            {
                "analysis": analysis,
                "timestamp": _scan_state["result_timestamp"],
                "mode": mode,
            },
            ttl_hours=_CACHE_TTL_HOURS,
        )

        stock_buys = len([p for p in analysis.get("stock_picks", []) if p.get("action") == "BUY"])
        crypto_buys = len([p for p in analysis.get("crypto_picks", []) if p.get("action") == "BUY"])
        logger.info(
            "Overnight scan complete: %d stock BUYs, %d crypto BUYs",
            stock_buys,
            crypto_buys,
        )
    except Exception as e:
        _scan_state["status"] = "error"
        _scan_state["error"] = str(e)
        logger.exception("Overnight scan failed")


@router.post("/start-scan")
async def start_overnight_scan(
    mode: ScanMode = Query(default=ScanMode.both),
    symbols: str = Query(default="", description="Comma-separated stock tickers (empty=defaults)"),
    crypto_pairs: str = Query(default="", description="Comma-separated crypto pairs (empty=defaults)"),
    current_positions: str = Query(default="", description="Comma-separated tickers you currently hold"),
) -> dict:
    """Kick off an overnight scan in the background."""
    with _scan_lock:
        if _scan_state["status"] == "scanning":
            return ok(
                {
                    "status": "already_scanning",
                    "progress": _scan_state["progress"],
                    "total": _scan_state["total"],
                    "step": _scan_state.get("step", ""),
                }
            )

        _scan_state["status"] = "scanning"
        _scan_state["progress"] = 0
        _scan_state["total"] = 0
        _scan_state["step"] = "Starting..."
        _scan_state["result"] = None
        _scan_state["error"] = None

    stock_list = [s.strip().upper() for s in symbols.split(",") if s.strip()] or DEFAULT_STOCKS
    crypto_list = [s.strip().upper() for s in crypto_pairs.split(",") if s.strip()] or DEFAULT_CRYPTO
    positions = [s.strip().upper() for s in current_positions.split(",") if s.strip()]

    _executor.submit(_run_scan_background, mode.value, stock_list, crypto_list, positions)
    return ok({"status": "started", "mode": mode.value})


@router.get("/status")
async def get_scan_status() -> dict:
    """Poll scan progress. Returns results when done."""
    status = _scan_state["status"]
    result = _scan_state["result"] if status == "done" else None
    result_timestamp = _scan_state.get("result_timestamp")
    from_cache = False

    if result is None and status == "idle":
        cached = data_cache.get(_CACHE_KEY)
        if cached and isinstance(cached, dict):
            result = cached.get("analysis")
            result_timestamp = cached.get("timestamp")
            from_cache = True

    return ok(
        {
            "status": status,
            "progress": _scan_state["progress"],
            "total": _scan_state["total"],
            "step": _scan_state.get("step", ""),
            "result": result,
            "result_timestamp": result_timestamp,
            "error": _scan_state["error"],
        },
        cached=from_cache,
    )


@router.get("/stream")
async def stream_overnight_scan():
    """SSE endpoint — streams progress in real-time, then the full result."""

    async def _event_stream():
        prev_snapshot = ""
        while True:
            snap: dict = {
                "status": _scan_state["status"],
                "progress": _scan_state["progress"],
                "total": _scan_state["total"],
                "step": _scan_state.get("step", ""),
                "error": _scan_state["error"],
            }

            if _scan_state["status"] == "done":
                snap["result"] = _scan_state["result"]
                snap["result_timestamp"] = _scan_state.get("result_timestamp")
                yield f"data: {json.dumps(snap, default=str)}\n\n"
                return

            if _scan_state["status"] == "error":
                yield f"data: {json.dumps(snap, default=str)}\n\n"
                return

            if _scan_state["status"] == "idle":
                cached = data_cache.get(_CACHE_KEY)
                if cached and isinstance(cached, dict):
                    snap["status"] = "done"
                    snap["result"] = cached.get("analysis")
                    snap["result_timestamp"] = cached.get("timestamp")
                    yield f"data: {json.dumps(snap, default=str)}\n\n"
                    return
                yield f"data: {json.dumps(snap, default=str)}\n\n"
                return

            encoded = json.dumps(snap, default=str)
            if encoded != prev_snapshot:
                yield f"data: {encoded}\n\n"
                prev_snapshot = encoded
            else:
                yield ": keepalive\n\n"

            await asyncio.sleep(0.8)

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/scorecard")
async def get_scorecard(
    days: int = Query(default=30, ge=1, le=90, description="Look-back period in days"),
) -> dict:
    """Performance scorecard — win rate, calibration, sector breakdown, recent picks."""
    return ok(compute_scorecard(days=days))


@router.post("/check-outcomes")
async def trigger_outcome_check() -> dict:
    """Manually trigger morning outcome checking for all pending picks."""
    resolved = check_morning_outcomes()
    scorecard = compute_scorecard(days=30)
    return ok({"resolved": resolved, "scorecard": scorecard})


@router.get("/history")
async def get_scan_history() -> dict:
    """Return Claude API cost log."""
    cost_log = data_cache.get("overnight:cost_log") or []

    total_cost = sum(e.get("cost_usd", 0) for e in cost_log)
    total_scans = len(cost_log)

    return ok(
        {
            "cost_log": cost_log[-20:],
            "cost_summary": {
                "total_scans": total_scans,
                "total_cost_usd": round(total_cost, 4),
                "avg_cost_per_scan": round(total_cost / total_scans, 4) if total_scans else 0,
            },
        }
    )

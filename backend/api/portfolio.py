"""Portfolio state endpoint — current positions, exposure, risk metrics."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from fastapi import APIRouter, Query

from backend.adaptive.vol_context import compute_vol_context
from backend.data.fetcher import DataFetcher
from backend.models.schemas import PortfolioState, Regime, StrategyName, TradeSignal
from backend.regime.detector import detect_regime
from backend.tracker.trade_journal import TradeJournal

router = APIRouter(prefix="/portfolio", tags=["portfolio"])
logger = logging.getLogger(__name__)
_fetcher = DataFetcher()
_journal = TradeJournal(fetcher=_fetcher)
_executor = ThreadPoolExecutor(max_workers=2)


@router.get("/state", response_model=PortfolioState)
async def get_portfolio_state() -> PortfolioState:
    """Current portfolio state including active trades and risk metrics."""
    vix_df = _fetcher.get_daily_ohlcv("^VIX", period="1y", live=True)
    spy_df = _fetcher.get_daily_ohlcv("SPY", period="1y", live=True)
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


def _build_quick_portfolio(capital: float) -> dict:
    """Combine sector recs + scanner signals, pick top 3, allocate dollars."""
    from backend.api.sectors import _analyze_sectors
    from backend.api.scanner import _run_scan

    vix_df = _fetcher.get_daily_ohlcv("^VIX", period="1y", live=True)
    spy_df = _fetcher.get_daily_ohlcv("SPY", period="1y", live=True)
    regime_result = detect_regime(vix_df, spy_df)
    regime: Regime = regime_result["regime"]
    vol = compute_vol_context(spy_df, vix_df)

    scored: dict[str, dict] = {}
    signal_map: dict[str, TradeSignal] = {}

    sector_data: dict = {}
    signals: list = []

    with ThreadPoolExecutor(max_workers=2) as pool:
        sector_future = pool.submit(_analyze_sectors)
        scanner_future = pool.submit(_run_scan, vol, regime)

        try:
            sector_data = sector_future.result()
        except Exception as e:
            logger.warning("Sector recs failed for quick portfolio: %s", e)

        try:
            signals = scanner_future.result()
        except Exception as e:
            logger.warning("Scanner failed for quick portfolio: %s", e)

    for pick in sector_data.get("stock_picks", []):
        ticker = pick["ticker"]
        scored[ticker] = {
            "ticker": ticker,
            "name": pick.get("name", ticker),
            "sector": pick.get("sector", "Unknown"),
            "price": pick.get("price", 0),
            "score": pick.get("score", 50),
            "why": pick.get("why", ""),
            "source": "sector",
        }

    for sig in signals:
        ticker = sig.ticker
        sig_score = sig.signal_score
        signal_map[ticker] = sig
        if ticker in scored:
            scored[ticker]["score"] = (scored[ticker]["score"] + sig_score) / 2 + 10
            scored[ticker]["source"] = "both"
            if sig.edge_reason:
                scored[ticker]["why"] += f"; signal: {sig.edge_reason}"
        else:
            price = sig.entry_price or _fetcher.get_current_price(ticker) or 0
            scored[ticker] = {
                "ticker": ticker,
                "name": ticker,
                "sector": "Unknown",
                "price": price,
                "score": sig_score,
                "why": sig.edge_reason or sig.strategy.value,
                "source": "scanner",
            }

    if not scored:
        return {"picks": [], "capital": capital, "regime": regime.value}

    ranked = sorted(scored.values(), key=lambda x: x["score"], reverse=True)[:3]

    total_score = sum(p["score"] for p in ranked)
    if total_score == 0:
        total_score = 1

    for p in ranked:
        ticker = p["ticker"]
        price = p["price"]
        raw_alloc = (p["score"] / total_score) * capital
        p["allocation_dollars"] = round(raw_alloc, 2)
        p["allocation_pct"] = round(raw_alloc / capital * 100, 1)
        p["shares"] = round(raw_alloc / price, 2) if price > 0 else 0

        if ticker in signal_map:
            sig = signal_map[ticker]
            p["direction"] = sig.direction
            p["entry"] = round(sig.entry_price, 2) if sig.entry_price else round(price, 2)
            p["stop_loss"] = round(sig.stop_loss, 2) if sig.stop_loss else None
            p["target"] = round(sig.target, 2) if sig.target else None
            p["strategy"] = sig.strategy.value
        else:
            p["direction"] = "long"
            p["entry"] = round(price, 2)
            p["strategy"] = "sector"

        if not p.get("stop_loss") or not p.get("target"):
            try:
                df = _fetcher.get_daily_ohlcv(ticker, period="3mo", live=True)
                if not df.empty and len(df) >= 14:
                    close = df["Close"]
                    high = df["High"]
                    low = df["Low"]
                    import pandas as pd
                    tr = pd.concat([
                        high - low,
                        (high - close.shift()).abs(),
                        (low - close.shift()).abs(),
                    ], axis=1).max(axis=1)
                    atr = float(tr.tail(14).mean())
                    if not p.get("stop_loss"):
                        p["stop_loss"] = round(price - atr * 1.5, 2)
                    if not p.get("target"):
                        p["target"] = round(price + atr * 2.5, 2)
            except Exception:
                if not p.get("stop_loss"):
                    p["stop_loss"] = round(price * 0.95, 2)
                if not p.get("target"):
                    p["target"] = round(price * 1.08, 2)

        entry = p["entry"]
        stop = p.get("stop_loss", entry * 0.95)
        target = p.get("target", entry * 1.08)
        p["risk_pct"] = round(abs(entry - stop) / entry * 100, 1) if entry > 0 else 0
        p["reward_pct"] = round(abs(target - entry) / entry * 100, 1) if entry > 0 else 0
        risk = abs(entry - stop)
        reward = abs(target - entry)
        p["risk_reward"] = round(reward / risk, 1) if risk > 0 else 0

    allocated = sum(p["allocation_dollars"] for p in ranked)
    if ranked and abs(allocated - capital) > 0.01:
        ranked[0]["allocation_dollars"] = round(
            ranked[0]["allocation_dollars"] + (capital - allocated), 2
        )

    return {
        "picks": ranked,
        "capital": capital,
        "regime": regime.value,
    }


@router.get("/quick-allocate")
async def quick_allocate(
    capital: float = Query(default=1000.0, ge=10.0, le=10_000_000.0),
) -> dict:
    """Synchronous version. Use /quick-allocate/start + /quick-allocate/status for async."""
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _build_quick_portfolio, capital)


# ── Background portfolio build ──

_portfolio_state: dict = {
    "status": "idle",
    "progress": 0,
    "total": 4,
    "step": "",
    "result": None,
    "result_timestamp": None,
    "error": None,
}


def _run_portfolio_background(capital: float) -> None:
    global _portfolio_state
    try:
        _portfolio_state["status"] = "scanning"
        _portfolio_state["error"] = None
        _portfolio_state["progress"] = 0
        _portfolio_state["total"] = 4
        _portfolio_state["step"] = "Detecting market regime..."

        from backend.api.sectors import _analyze_sectors
        from backend.api.scanner import _run_scan

        vix_df = _fetcher.get_daily_ohlcv("^VIX", period="1y", live=True)
        spy_df = _fetcher.get_daily_ohlcv("SPY", period="1y", live=True)
        regime_result = detect_regime(vix_df, spy_df)
        regime: Regime = regime_result["regime"]
        vol = compute_vol_context(spy_df, vix_df)
        _portfolio_state["progress"] = 1
        _portfolio_state["step"] = "Analyzing sectors and scanning signals (parallel)..."

        scored: dict[str, dict] = {}
        signal_map: dict[str, TradeSignal] = {}

        sector_data: dict = {}
        signals: list = []

        with ThreadPoolExecutor(max_workers=2) as pool:
            sector_future = pool.submit(_analyze_sectors)
            scanner_future = pool.submit(_run_scan, vol, regime)

            try:
                sector_data = sector_future.result()
            except Exception as e:
                logger.warning("Sector recs failed for quick portfolio: %s", e)

            try:
                signals = scanner_future.result()
            except Exception as e:
                logger.warning("Scanner failed for quick portfolio: %s", e)

        for pick in sector_data.get("stock_picks", []):
            ticker = pick["ticker"]
            scored[ticker] = {
                "ticker": ticker,
                "name": pick.get("name", ticker),
                "sector": pick.get("sector", "Unknown"),
                "price": pick.get("price", 0),
                "score": pick.get("score", 50),
                "why": pick.get("why", ""),
                "source": "sector",
            }

        for sig in signals:
            ticker = sig.ticker
            sig_score = sig.signal_score
            signal_map[ticker] = sig
            if ticker in scored:
                scored[ticker]["score"] = (scored[ticker]["score"] + sig_score) / 2 + 10
                scored[ticker]["source"] = "both"
                if sig.edge_reason:
                    scored[ticker]["why"] += f"; signal: {sig.edge_reason}"
            else:
                price = sig.entry_price or _fetcher.get_current_price(ticker) or 0
                scored[ticker] = {
                    "ticker": ticker,
                    "name": ticker,
                    "sector": "Unknown",
                    "price": price,
                    "score": sig_score,
                    "why": sig.edge_reason or sig.strategy.value,
                    "source": "scanner",
                }

        _portfolio_state["progress"] = 3
        _portfolio_state["step"] = "Building entry/exit plans..."

        if not scored:
            _portfolio_state["result"] = {"picks": [], "capital": capital, "regime": regime.value}
            _portfolio_state["status"] = "done"
            return

        ranked = sorted(scored.values(), key=lambda x: x["score"], reverse=True)[:3]
        total_score = sum(p["score"] for p in ranked) or 1

        raw_pcts = [(p["score"] / total_score) * 100 for p in ranked]
        int_pcts = [int(pct) for pct in raw_pcts]
        remainder = 100 - sum(int_pcts)
        fractional = [(raw_pcts[i] - int_pcts[i], i) for i in range(len(ranked))]
        fractional.sort(reverse=True)
        for j in range(remainder):
            int_pcts[fractional[j][1]] += 1

        for idx, p in enumerate(ranked):
            ticker = p["ticker"]
            price = p["price"]
            pct = int_pcts[idx]
            alloc = round(capital * pct / 100, 2)
            p["allocation_dollars"] = alloc
            p["allocation_pct"] = pct
            p["shares"] = round(alloc / price, 2) if price > 0 else 0

            p["direction"] = "long"
            p["entry"] = round(price, 2)
            p["hold_period"] = "6-12 months"

            if ticker in signal_map:
                sig = signal_map[ticker]
                if sig.edge_reason:
                    pass
                p["strategy"] = sig.strategy.value
            else:
                p["strategy"] = "sector"

            p["target"] = round(price * 1.30, 2)
            p["stop_loss"] = round(price * 0.85, 2)

            entry = p["entry"]
            stop = p["stop_loss"]
            target = p["target"]
            p["risk_pct"] = round(abs(entry - stop) / entry * 100, 1) if entry > 0 else 0
            p["reward_pct"] = round(abs(target - entry) / entry * 100, 1) if entry > 0 else 0
            risk = abs(entry - stop)
            reward = abs(target - entry)
            p["risk_reward"] = round(reward / risk, 1) if risk > 0 else 0

        result = {"picks": ranked, "capital": capital, "regime": regime.value}
        _portfolio_state["result"] = result
        _portfolio_state["result_timestamp"] = datetime.utcnow().isoformat()
        _portfolio_state["progress"] = 4
        _portfolio_state["step"] = "Done"
        _portfolio_state["status"] = "done"
        from backend.data.cache import data_cache
        data_cache.set("portfolio:last_result", result, ttl_hours=24.0)
        logger.info("Background portfolio build done: %d picks", len(ranked))
    except Exception as e:
        _portfolio_state["status"] = "error"
        _portfolio_state["error"] = str(e)
        logger.exception("Background portfolio build failed")


@router.post("/quick-allocate/start")
async def start_portfolio_build(
    capital: float = Query(default=1000.0, ge=10.0, le=10_000_000.0),
) -> dict:
    """Kick off portfolio build in the background."""
    if _portfolio_state["status"] == "scanning":
        return {"status": "already_scanning"}

    _portfolio_state["status"] = "scanning"
    _portfolio_state["progress"] = 0
    _portfolio_state["step"] = ""
    _portfolio_state["result"] = None
    _executor.submit(_run_portfolio_background, capital)
    return {"status": "started"}


@router.get("/quick-allocate/status")
async def get_portfolio_build_status() -> dict:
    """Poll portfolio build progress."""
    result = _portfolio_state["result"] if _portfolio_state["status"] == "done" else None

    if result is None and _portfolio_state["status"] == "idle":
        from backend.data.cache import data_cache
        cached = data_cache.get("portfolio:last_result")
        if cached:
            result = cached
            _portfolio_state["status"] = "done"
            _portfolio_state["result"] = cached
            if not _portfolio_state.get("result_timestamp"):
                _portfolio_state["result_timestamp"] = datetime.utcnow().isoformat()

    return {
        "status": _portfolio_state["status"],
        "progress": _portfolio_state["progress"],
        "total": _portfolio_state["total"],
        "step": _portfolio_state["step"],
        "result": result,
        "result_timestamp": _portfolio_state.get("result_timestamp"),
        "error": _portfolio_state["error"],
    }

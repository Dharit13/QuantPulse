"""Portfolio state endpoint — current positions, exposure, risk metrics.

AI investment research is generated server-side as part of the portfolio
pipeline so the frontend receives complete results in a single SSE stream.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import UTC, datetime

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from backend.adaptive.vol_context import compute_vol_context
from backend.adaptive.weight_interpolation import compute_blended_weights
from backend.ai.market_ai import ai_investment_research
from backend.data.fetcher import DataFetcher
from backend.models.schemas import PortfolioState, Regime, StrategyName, TradeSignal
from backend.regime.detector import detect_regime
from backend.risk.correlation import check_new_position_correlation
from backend.risk.manager import risk_manager
from backend.risk.var import compute_portfolio_var
from backend.tracker.strategy_health import compute_strategy_health
from backend.tracker.trade_journal import TradeJournal

STRATEGY_WEIGHT_MAP = {
    "stat_arb": "stat_arb",
    "catalyst": "catalyst",
    "catalyst_event": "catalyst",
    "cross_asset": "momentum",
    "cross_asset_momentum": "momentum",
    "flow": "flow",
    "flow_imbalance": "flow",
    "intraday": "intraday",
    "gap_reversion": "intraday",
}

router = APIRouter(prefix="/portfolio", tags=["portfolio"])
logger = logging.getLogger(__name__)
_fetcher = DataFetcher()
_journal = TradeJournal(fetcher=_fetcher)
_executor = ThreadPoolExecutor(max_workers=2)


@router.get("/state")
async def get_portfolio_state(
    refresh: bool = False,
) -> dict:
    """Current portfolio state from pipeline cache (instant) or live."""
    if not refresh:
        from backend.data.cache import data_cache

        cached = data_cache.get("pipeline:portfolio")
        if cached and isinstance(cached, dict):
            return cached

    from backend.pipeline import refresh_portfolio

    result = refresh_portfolio()
    if result:
        return result

    vix_df = _fetcher.get_daily_ohlcv("^VIX", period="1y", live=False)
    spy_df = _fetcher.get_daily_ohlcv("SPY", period="1y", live=False)
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

    # Real VaR from active positions
    daily_var = 0.0
    if active_entries:
        try:
            from backend.risk.correlation import compute_position_returns

            tickers = [t.ticker for t in active_entries]
            weights = {t.ticker: t.position_size_pct / 100.0 for t in active_entries}
            pos_returns = compute_position_returns(tickers, lookback_days=60)
            var_result = compute_portfolio_var(pos_returns, weights, confidence=0.95)
            daily_var = abs(var_result.get("portfolio_var_95", 0.0))
        except Exception:
            pass

    current_drawdown_pct = abs(risk_manager._compute_drawdown())

    return {
        "data": PortfolioState(
            regime=regime,
            regime_confidence=confidence,
            gross_exposure=round(gross, 4),
            net_exposure=round(net, 4),
            daily_var=round(daily_var, 4),
            current_drawdown_pct=round(current_drawdown_pct, 4),
            active_trades=active_signals,
            strategy_pnl=strategy_pnl,
            total_pnl_ytd=summary.get("total_pnl_dollars", 0),
            portfolio_sharpe_30d=0.0,
        ).model_dump(mode="json"),
        "refreshed_at": datetime.now(UTC).isoformat(),
    }


@router.get("/alerts")
async def check_alerts() -> list[dict]:
    """Check active trades for stop/target/time alerts."""
    return _journal.check_active_trade_alerts()


def _build_quick_portfolio(capital: float) -> dict:
    """Combine sector recs + scanner signals, pick top 3, allocate dollars."""
    from backend.api.scanner import _run_scan
    from backend.api.sectors import _analyze_sectors

    vix_df = _fetcher.get_daily_ohlcv("^VIX", period="1y", live=False)
    spy_df = _fetcher.get_daily_ohlcv("SPY", period="1y", live=False)
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
            sector_data = sector_future.result(timeout=180)
        except (TimeoutError, Exception) as e:
            logger.warning("Sector recs failed/timed out for quick portfolio: %s", e)

        try:
            signals = scanner_future.result(timeout=180)
        except (TimeoutError, Exception) as e:
            logger.warning("Scanner failed/timed out for quick portfolio: %s", e)

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
                df = _fetcher.get_daily_ohlcv(ticker, period="3mo", live=False)
                if not df.empty and len(df) >= 14:
                    close = df["Close"]
                    high = df["High"]
                    low = df["Low"]
                    import pandas as pd

                    tr = pd.concat(
                        [
                            high - low,
                            (high - close.shift()).abs(),
                            (low - close.shift()).abs(),
                        ],
                        axis=1,
                    ).max(axis=1)
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
        ranked[0]["allocation_dollars"] = round(ranked[0]["allocation_dollars"] + (capital - allocated), 2)

    return {
        "picks": ranked,
        "capital": capital,
        "regime": regime.value,
    }


@router.get("/quick-allocate")
async def quick_allocate(
    capital: float = Query(default=1000.0, ge=10.0, le=10_000_000.0),
    refresh: bool = Query(False, description="Force live computation, bypass pipeline cache"),
) -> dict:
    """Quick portfolio allocation from pipeline cache or live."""
    if not refresh:
        from backend.data.cache import data_cache

        cached = data_cache.get("portfolio:last_result")
        if cached and isinstance(cached, dict):
            return {"data": cached, "refreshed_at": cached.get("timestamp", datetime.now(UTC).isoformat())}

    import asyncio

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, _build_quick_portfolio, capital)
    return {"data": result, "refreshed_at": datetime.now(UTC).isoformat()}


# ── Background portfolio build ──

_portfolio_state: dict = {
    "status": "idle",
    "progress": 0,
    "total": 100,
    "step": "",
    "result": None,
    "result_timestamp": None,
    "ai_research": None,
    "error": None,
}


def _sentiment_candidates(scored: dict[str, dict], wf_params: dict) -> list[dict]:
    """Pull top bullish tickers from FinBERT sentiment cache.

    *wf_params* comes from ``get_portfolio_waterfall_params(vol)`` so
    thresholds adapt to the current volatility regime.
    """
    min_score = wf_params["sentiment_min_score"]
    max_candidates = wf_params["max_sentiment_candidates"]

    try:
        from backend.data.sentiment_cache import sentiment_cache

        candidates: list[dict] = []
        for ticker in sentiment_cache.all_tickers():
            if ticker in scored:
                continue
            entry = sentiment_cache.get(ticker)
            if not entry or entry.composite_score <= min_score:
                continue
            price = 0.0
            try:
                price = _fetcher.get_current_price(ticker) or 0.0
            except Exception:
                pass
            if price <= 0:
                continue
            candidates.append({
                "ticker": ticker,
                "name": ticker,
                "sector": "Unknown",
                "price": price,
                "score": entry.composite_score,
                "why": f"FinBERT sentiment {entry.composite_score:.0f}/100 ({entry.sentiment_label})",
                "source": "sentiment",
            })
        candidates.sort(key=lambda c: c["score"], reverse=True)
        return candidates[:max_candidates]
    except Exception as exc:
        logger.debug("Sentiment candidates unavailable: %s", exc)
        return []


def _bluechip_fallback(scored: dict[str, dict]) -> list[dict]:
    """Score blue-chip tickers by 20d momentum as a guaranteed fallback."""
    from backend.config import settings

    bluechip_tickers = [t.strip() for t in settings.portfolio_bluechip_tickers.split(",") if t.strip()]

    candidates: list[dict] = []
    for ticker in bluechip_tickers:
        if ticker in scored:
            continue
        try:
            df = _fetcher.get_daily_ohlcv(ticker, period="3mo", live=False)
            if df.empty or len(df) < 20:
                continue
            close = df["Close"]
            price = float(close.iloc[-1])
            ret_20d = float((close.iloc[-1] / close.iloc[-20] - 1) * 100)
            score = max(10.0, min(90.0, 50 + ret_20d * 2))
            candidates.append({
                "ticker": ticker,
                "name": ticker,
                "sector": "Unknown",
                "price": price,
                "score": round(score, 1),
                "why": f"Blue-chip momentum: {ret_20d:+.1f}% (20d)",
                "source": "bluechip",
            })
        except Exception:
            continue
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates


def _sector_dedup(scored: dict[str, dict], wf_params: dict) -> dict[str, dict]:
    """Keep at most *wf_params["max_per_sector"]* candidates per sector."""
    max_per_sector = wf_params["max_per_sector"]

    ranked = sorted(scored.values(), key=lambda c: c.get("score", 0), reverse=True)
    sector_counts: dict[str, int] = {}
    result: dict[str, dict] = {}
    for c in ranked:
        sec = c.get("sector", "Unknown")
        cnt = sector_counts.get(sec, 0)
        if sec != "Unknown" and cnt >= max_per_sector:
            continue
        result[c["ticker"]] = c
        sector_counts[sec] = cnt + 1
    return result


def _run_portfolio_background(capital: float) -> None:
    from backend.progress import ScanProgressTracker

    global _portfolio_state
    try:
        _portfolio_state["status"] = "scanning"
        _portfolio_state["error"] = None
        _portfolio_state["ai_research"] = None

        tracker = ScanProgressTracker.create(
            [
                ("regime", 5),
                ("scan", 180),
                ("build", 5),
                ("ai_research", 30),
            ],
            _portfolio_state,
            "progress:portfolio",
        )

        tracker.start_phase("regime", "Detecting market regime...")

        from backend.api.scanner import _run_scan
        from backend.api.sectors import _analyze_sectors

        vix_df = _fetcher.get_daily_ohlcv("^VIX", period="1y", live=False)
        spy_df = _fetcher.get_daily_ohlcv("SPY", period="1y", live=False)
        regime_result = detect_regime(vix_df, spy_df)
        regime: Regime = regime_result["regime"]
        vol = compute_vol_context(spy_df, vix_df)

        tracker.start_phase("scan", "Analyzing sectors and scanning signals...")

        scan_timeout_sec = 600

        scored: dict[str, dict] = {}
        signal_map: dict[str, TradeSignal] = {}

        sector_data: dict = {}
        signals: list = []

        # Reuse cached scanner results when available to avoid duplicate scans
        from backend.data.cache import data_cache

        cached_scan = data_cache.get("scanner:last_result")
        cached_signals: list[TradeSignal] = []
        if cached_scan and isinstance(cached_scan, dict):
            for es in cached_scan.get("signals", []):
                sig_data = es.get("signal", {}) if isinstance(es, dict) else {}
                if sig_data:
                    try:
                        cached_signals.append(TradeSignal(**sig_data))
                    except Exception:
                        pass
            if cached_signals:
                logger.info("Portfolio reusing %d cached scanner signals", len(cached_signals))

        with ThreadPoolExecutor(max_workers=2) as pool:
            sector_future = pool.submit(_analyze_sectors)
            scanner_future = None
            if not cached_signals:
                scanner_future = pool.submit(_run_scan, vol, regime)

            remaining: float = scan_timeout_sec
            scan_start = time.time()

            try:
                sector_data = sector_future.result(timeout=remaining)
            except (TimeoutError, Exception) as e:
                logger.warning("Sector recs failed/timed out for portfolio: %s", e)

            if cached_signals:
                signals = cached_signals
            elif scanner_future is not None:
                remaining = max(10, scan_timeout_sec - (time.time() - scan_start))
                try:
                    signals = scanner_future.result(timeout=remaining)
                except (TimeoutError, Exception) as e:
                    logger.warning("Scanner failed/timed out for portfolio: %s", e)
                    pool.shutdown(wait=False, cancel_futures=True)

        # ── Adaptive waterfall params (scaled by VolContext) ──
        from backend.adaptive.thresholds import get_portfolio_waterfall_params

        wf_params = get_portfolio_waterfall_params(vol)
        logger.info(
            "Portfolio waterfall params (vol_scale=%.2f): sent_min=%.0f, max_sent=%d, max_sector=%d, max_picks=%d",
            vol.vol_scale,
            wf_params["sentiment_min_score"],
            wf_params["max_sentiment_candidates"],
            wf_params["max_per_sector"],
            wf_params["max_picks"],
        )

        # ── Priority waterfall: signals > sentiment > sectors > blue-chip ──

        # Layer 1: Strategy signals (highest priority)
        for sig in signals:
            ticker = sig.ticker
            signal_map[ticker] = sig
            price = sig.entry_price or _fetcher.get_current_price(ticker) or 0
            scored[ticker] = {
                "ticker": ticker,
                "name": ticker,
                "sector": "Unknown",
                "price": price,
                "score": sig.signal_score,
                "why": sig.edge_reason or sig.strategy.value,
                "source": "scanner",
            }

        # Layer 2: FinBERT sentiment leaders (adaptive threshold)
        sentiment_adds = _sentiment_candidates(scored, wf_params)
        for cand in sentiment_adds:
            scored[cand["ticker"]] = cand
        if sentiment_adds:
            logger.info("Portfolio waterfall: added %d sentiment candidates", len(sentiment_adds))

        # Layer 3: Sector momentum leaders (lower priority than signals/sentiment)
        for pick in sector_data.get("stock_picks", []):
            ticker = pick["ticker"]
            if ticker in scored:
                scored[ticker]["score"] = (scored[ticker]["score"] + pick.get("score", 50)) / 2 + 5
                scored[ticker]["source"] = "both"
                if pick.get("why"):
                    scored[ticker]["why"] += f"; sector: {pick['why']}"
                if pick.get("sector"):
                    scored[ticker]["sector"] = pick["sector"]
            else:
                scored[ticker] = {
                    "ticker": ticker,
                    "name": pick.get("name", ticker),
                    "sector": pick.get("sector", "Unknown"),
                    "price": pick.get("price", 0),
                    "score": pick.get("score", 50),
                    "why": pick.get("why", ""),
                    "source": "sector",
                }

        # Layer 4: Blue-chip fallback (always produces candidates)
        if len(scored) < wf_params["min_candidates"]:
            logger.info(
                "Portfolio waterfall: fewer than %d candidates, adding blue-chip fallbacks...",
                wf_params["min_candidates"],
            )
            for cand in _bluechip_fallback(scored):
                scored[cand["ticker"]] = cand
                if len(scored) >= wf_params["max_picks"]:
                    break

        # Sector dedup to ensure diversification (adaptive limit)
        scored = _sector_dedup(scored, wf_params)

        sector_picks = sector_data.get("stock_picks", [])
        logger.info(
            "Portfolio waterfall: %d signals, %d sentiment, %d sector picks, %d blue-chip → %d total (after dedup)",
            len(signals),
            len(sentiment_adds),
            len(sector_picks),
            sum(1 for c in scored.values() if c.get("source") == "bluechip"),
            len(scored),
        )

        tracker.start_phase("build", "Building regime-weighted allocation...")

        if not scored:
            _portfolio_state["result"] = {"picks": [], "capital": capital, "regime": regime.value}
            _portfolio_state["status"] = "done"
            return

        # Get regime strategy weights for allocation
        regime_result_full = detect_regime(vix_df, spy_df)
        regime_probs = regime_result_full.get("probabilities", {regime.value: 1.0})
        strategy_weights = compute_blended_weights(regime_probs)

        max_position_pct = 0.08

        # ── Strategy health gating ──
        strategy_health_map: dict[str, dict] = {}
        for strat in StrategyName:
            try:
                health = compute_strategy_health(strat.value, current_regime=regime.value)
                strategy_health_map[strat.value] = {
                    "status": health.status,
                    "sharpe_60d": health.rolling_sharpe_60d,
                    "win_rate_60d": health.rolling_win_rate_60d,
                    "size_adjustment": health.size_adjustment,
                }
            except Exception:
                strategy_health_map[strat.value] = {
                    "status": "unknown",
                    "sharpe_60d": 0.0,
                    "win_rate_60d": 0.0,
                    "size_adjustment": 1.0,
                }

        # ── Fetch scanner enrichment cache for shadow sizing ──
        enriched_cache: dict[str, dict] = {}
        try:
            from backend.data.cache import data_cache as _dc

            scanner_result = _dc.get("scanner:last_result")
            if scanner_result and isinstance(scanner_result, dict):
                for es in scanner_result.get("signals", []):
                    sig_data = es.get("signal", {}) if isinstance(es, dict) else {}
                    tk = sig_data.get("ticker", "")
                    if tk:
                        enriched_cache[tk] = es
        except Exception:
            pass

        # Score each candidate using conviction * strategy weight
        for ticker_key, info in scored.items():
            sig = signal_map.get(ticker_key)
            if sig:
                strat_name = sig.strategy.value
                weight_key = STRATEGY_WEIGHT_MAP.get(strat_name, "catalyst")
                strat_weight = strategy_weights.get(weight_key, 0.10)
                kelly_pct = (sig.kelly_size_pct or 2.0) / 100.0
                info["_conviction_rank"] = (sig.conviction or 0.5) * strat_weight
                info["_kelly_pct"] = min(kelly_pct * strat_weight, max_position_pct)
                info["_strategy"] = strat_name
            else:
                info["_conviction_rank"] = info["score"] / 100.0 * 0.10
                info["_kelly_pct"] = 0.03
                info["_strategy"] = "sector"

        ranked_candidates = sorted(
            scored.values(),
            key=lambda x: x["_conviction_rank"],
            reverse=True,
        )

        # ── Filter by strategy health ──
        health_filtered: list[dict] = []
        health_skipped: list[str] = []
        for cand in ranked_candidates:
            strat = cand["_strategy"]
            h = strategy_health_map.get(strat, {})
            status = h.get("status", "unknown")
            if status == "paused":
                health_skipped.append(f"{cand['ticker']} ({strat} paused)")
                continue
            if status == "degraded":
                cand["_kelly_pct"] *= h.get("size_adjustment", 0.5)
            health_filtered.append(cand)

        # ── Correlation dedup (spec §12 Step 3) ──
        # Limit to top 15 candidates before expensive correlation checks
        top_candidates = health_filtered[:15]
        accepted_tickers: list[str] = []
        correlation_dropped: list[str] = []
        corr_filtered: list[dict] = []

        for cand in top_candidates:
            ticker = cand["ticker"]
            if accepted_tickers:
                try:
                    corr_check = check_new_position_correlation(
                        ticker,
                        accepted_tickers,
                    )
                    if not corr_check["approved"]:
                        existing = corr_check["most_correlated_with"]
                        correlation_dropped.append(
                            f"{ticker} dropped (corr {corr_check['max_correlation']:.2f} with {existing})"
                        )
                        continue
                    if corr_check["size_haircut"] < 1.0:
                        cand["_kelly_pct"] *= corr_check["size_haircut"]
                except Exception:
                    pass

            corr_filtered.append(cand)
            accepted_tickers.append(ticker)

        ranked = corr_filtered[:wf_params["max_picks"]]
        logger.info(
            "Portfolio filters: %d ranked -> %d health -> %d corr -> %d final (top %d), dropped=%s",
            len(ranked_candidates),
            len(health_filtered),
            len(corr_filtered),
            len(ranked),
            wf_params["max_picks"],
            correlation_dropped or "none",
        )

        # ── Risk manager check for each proposed position (spec §11) ──
        approved_picks: list[dict] = []
        risk_rejected: list[str] = []
        active_trade_signals: list[TradeSignal] = []
        sector_exposures: dict[str, float] = {}

        for p in ranked:
            ticker = p["ticker"]
            sig = signal_map.get(ticker)
            if sig:
                risk_result = risk_manager.check_trade(
                    signal=sig,
                    vol=vol,
                    active_trades=active_trade_signals,
                    sector_exposures=sector_exposures,
                )
                if not risk_result["approved"]:
                    risk_rejected.append(f"{ticker}: {'; '.join(risk_result['reasons'])}")
                    continue
                if risk_result["adjusted_size"] < (sig.kelly_size_pct / 100):
                    p["_kelly_pct"] = min(p["_kelly_pct"], risk_result["adjusted_size"])
                p["risk_checks"] = {
                    "passed": True,
                    "warnings": risk_result["reasons"],
                }
                active_trade_signals.append(sig)
                try:
                    from backend.data.universe import get_ticker_sector

                    sec = get_ticker_sector(ticker)
                    sector_exposures[sec] = sector_exposures.get(sec, 0.0) + p["_kelly_pct"]
                except Exception:
                    pass
            else:
                p["risk_checks"] = {"passed": True, "warnings": ["No signal — sector pick"]}

            approved_picks.append(p)

        ranked = approved_picks

        # ── Shadow evidence sizing ──
        for p in ranked:
            ticker = p["ticker"]
            es = enriched_cache.get(ticker)
            if es and isinstance(es, dict):
                ssf = es.get("shadow_size_factor", 1.0)
                if ssf < 1.0:
                    p["_kelly_pct"] *= ssf

        # ── Allocate capital using Kelly-weighted sizing, capped at 8% per position ──
        cash_weight = strategy_weights.get("cash", 0.05)
        investable_capital = capital * (1.0 - cash_weight)

        total_kelly = sum(p["_kelly_pct"] for p in ranked) or 1.0

        for p in ranked:
            ticker = p["ticker"]
            price = p["price"]
            alloc_pct = min(p["_kelly_pct"] / total_kelly, max_position_pct)
            alloc = round(investable_capital * alloc_pct * len(ranked), 2)
            alloc = min(alloc, investable_capital * max_position_pct)

            p["allocation_dollars"] = alloc
            p["allocation_pct"] = round(alloc / capital * 100, 1) if capital > 0 else 0
            p["shares"] = round(alloc / price, 2) if price > 0 else 0

            sig = signal_map.get(ticker)
            p["direction"] = sig.direction if sig else "long"
            p["entry"] = round(sig.entry_price, 2) if sig and sig.entry_price else round(price, 2)
            hold_days = sig.max_hold_days if sig else 0
            if hold_days <= 5:
                p["hold_period"] = "1-5 days" if hold_days > 0 else "6-12 months"
            elif hold_days <= 14:
                p["hold_period"] = "1-2 weeks"
            elif hold_days <= 30:
                p["hold_period"] = "2-4 weeks"
            elif hold_days <= 90:
                p["hold_period"] = "1-3 months"
            else:
                p["hold_period"] = "6-12 months"
            p["strategy"] = p["_strategy"]

            if sig and sig.stop_loss:
                p["stop_loss"] = round(sig.stop_loss, 2)
            else:
                p["stop_loss"] = round(price * 0.92, 2)
            if sig and sig.target:
                p["target"] = round(sig.target, 2)
            else:
                p["target"] = round(price * 1.15, 2)

            entry = p["entry"]
            stop = p["stop_loss"]
            target = p["target"]
            p["risk_pct"] = round(abs(entry - stop) / entry * 100, 1) if entry > 0 else 0
            p["reward_pct"] = round(abs(target - entry) / entry * 100, 1) if entry > 0 else 0
            risk = abs(entry - stop)
            reward = abs(target - entry)
            p["risk_reward"] = round(reward / risk, 1) if risk > 0 else 0

        # ── Portfolio VaR and Sharpe checks (spec §11 L3, §12 Step 5-6) ──
        portfolio_var_pct = 0.0
        expected_sharpe = 0.0
        var_adjusted = False
        sharpe_adjusted = False

        if ranked:
            pick_tickers = [p["ticker"] for p in ranked]
            pick_weights = {}
            for p in ranked:
                pick_weights[p["ticker"]] = p["allocation_pct"] / 100.0

            try:
                from backend.risk.correlation import compute_position_returns

                pos_returns = compute_position_returns(pick_tickers, lookback_days=60)
                var_result = compute_portfolio_var(pos_returns, pick_weights, confidence=0.95, vol=vol)
                portfolio_var_pct = abs(var_result.get("portfolio_var_95", 0.0))

                if var_result.get("breaches_2pct_limit", False) and portfolio_var_pct > 0:
                    scale_down = 0.02 / portfolio_var_pct
                    for p in ranked:
                        p["allocation_dollars"] = round(p["allocation_dollars"] * scale_down, 2)
                        p["allocation_pct"] = round(p["allocation_dollars"] / capital * 100, 1)
                        p["shares"] = round(p["allocation_dollars"] / p["price"], 2) if p["price"] > 0 else 0
                    portfolio_var_pct = 0.02
                    var_adjusted = True
            except Exception as e:
                logger.debug("Portfolio VaR check failed: %s", e)

            # Expected portfolio Sharpe
            try:
                weight_arr = []
                sharpe_arr = []
                var_arr = []
                for p in ranked:
                    w = p["allocation_pct"] / 100.0
                    sig = signal_map.get(p["ticker"])
                    s = sig.expected_sharpe if sig and sig.expected_sharpe > 0 else 1.0
                    weight_arr.append(w)
                    sharpe_arr.append(s)
                    var_arr.append(w * w * 1.0)
                weighted_sharpe = sum(w * s for w, s in zip(weight_arr, sharpe_arr))
                port_vol = math.sqrt(sum(var_arr))
                expected_sharpe = weighted_sharpe / port_vol if port_vol > 0 else 0.0

                if expected_sharpe < 1.5 and len(ranked) > 1:
                    ranked[-1]["allocation_dollars"] = round(ranked[-1]["allocation_dollars"] * 0.5, 2)
                    ranked[-1]["allocation_pct"] = round(ranked[-1]["allocation_dollars"] / capital * 100, 1)
                    ranked[-1]["shares"] = (
                        round(ranked[-1]["allocation_dollars"] / ranked[-1]["price"], 2)
                        if ranked[-1]["price"] > 0
                        else 0
                    )
                    sharpe_adjusted = True
            except Exception as e:
                logger.debug("Expected Sharpe computation failed: %s", e)

        # Clean up internal keys
        for p in ranked:
            p.pop("_conviction_rank", None)
            p.pop("_kelly_pct", None)
            p.pop("_strategy", None)

        # Normalize allocations so they sum to investable capital
        total_alloc = sum(p["allocation_dollars"] for p in ranked)
        if total_alloc > 0 and abs(total_alloc - investable_capital) > 1.0:
            scale = investable_capital / total_alloc
            for p in ranked:
                p["allocation_dollars"] = round(p["allocation_dollars"] * scale, 2)
                p["allocation_pct"] = round(p["allocation_dollars"] / capital * 100, 1)
                p["shares"] = round(p["allocation_dollars"] / p["price"], 2) if p["price"] > 0 else 0

        result = {
            "picks": ranked,
            "capital": capital,
            "regime": regime.value,
            "strategy_health": strategy_health_map,
            "correlation_dropped": correlation_dropped,
            "risk_rejected": risk_rejected,
            "health_skipped": health_skipped,
            "portfolio_var_pct": round(portfolio_var_pct, 4),
            "expected_sharpe": round(expected_sharpe, 2),
            "var_adjusted": var_adjusted,
            "sharpe_adjusted": sharpe_adjusted,
        }

        tracker.start_phase("ai_research", "AI building your investment plan...")
        ai_research = None
        try:
            ai_research = ai_investment_research(regime.value, capital, ranked)
        except Exception as e:
            logger.warning("AI investment research failed (scan continues): %s", e)

        tracker.finish()
        tracker.save_history("progress:portfolio")

        _portfolio_state["result"] = result
        _portfolio_state["result_timestamp"] = datetime.now(UTC).isoformat()
        _portfolio_state["ai_research"] = ai_research
        _portfolio_state["status"] = "done"
        from backend.data.cache import data_cache

        data_cache.set("portfolio:last_result", result, ttl_hours=24.0)
        data_cache.set("portfolio:ai_research", ai_research, ttl_hours=24.0)
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
    _portfolio_state["ai_research"] = None
    _executor.submit(_run_portfolio_background, capital)
    return {"status": "started"}


@router.get("/quick-allocate/status")
async def get_portfolio_build_status() -> dict:
    """Poll portfolio build progress."""
    status = _portfolio_state["status"]
    result = _portfolio_state["result"] if status == "done" else None
    ai_research = _portfolio_state.get("ai_research")
    result_timestamp = _portfolio_state.get("result_timestamp")
    cached_at: str | None = None

    if result is None and status == "idle":
        from backend.data.cache import data_cache

        cached = data_cache.get("portfolio:last_result")
        if cached:
            result = cached
            ai_research = data_cache.get("portfolio:ai_research")
            cached_at = datetime.now(UTC).isoformat()
            result_timestamp = result_timestamp or cached_at

    return {
        "status": status,
        "progress": _portfolio_state["progress"],
        "total": _portfolio_state["total"],
        "step": _portfolio_state.get("step", ""),
        "result": result,
        "result_timestamp": result_timestamp,
        "cached_at": cached_at,
        "ai_summary": ai_research,
        "error": _portfolio_state["error"],
    }


@router.get("/quick-allocate/stream")
async def stream_portfolio_build():
    """SSE endpoint — streams portfolio build progress in real-time."""

    async def _event_stream():
        prev_snapshot = ""
        while True:
            snap = {
                "status": _portfolio_state["status"],
                "progress": _portfolio_state["progress"],
                "total": _portfolio_state["total"],
                "step": _portfolio_state.get("step", ""),
                "error": _portfolio_state["error"],
            }
            encoded = json.dumps(snap, default=str)

            if _portfolio_state["status"] == "done":
                snap["result"] = _portfolio_state["result"]
                snap["result_timestamp"] = _portfolio_state.get("result_timestamp")
                snap["ai_summary"] = _portfolio_state.get("ai_research")
                yield f"data: {json.dumps(snap, default=str)}\n\n"
                return

            if _portfolio_state["status"] == "error":
                yield f"data: {encoded}\n\n"
                return

            if _portfolio_state["status"] == "idle":
                from backend.data.cache import data_cache

                cached = data_cache.get("portfolio:last_result")
                if cached:
                    snap["status"] = "done"
                    snap["result"] = cached
                    snap["result_timestamp"] = _portfolio_state.get("result_timestamp")
                    snap["ai_summary"] = data_cache.get("portfolio:ai_research")
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

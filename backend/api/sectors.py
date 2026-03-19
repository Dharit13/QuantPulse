"""Sector analysis — which sectors to invest in for the next 30 days."""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
from fastapi import APIRouter, Query

from backend.adaptive.vol_context import compute_vol_context
from backend.data.cross_asset import SECTOR_ETFS
from backend.data.fetcher import DataFetcher
from backend.data.universe import fetch_sp500_constituents
from backend.regime.detector import detect_regime

router = APIRouter(prefix="/sectors", tags=["sectors"])
logger = logging.getLogger(__name__)
_fetcher = DataFetcher()
_executor = ThreadPoolExecutor(max_workers=2)

TOP_PICKS_PER_SECTOR = 3

_CACHE_TTL_SECONDS = 15 * 60  # 15 minutes
_cached_result: dict | None = None
_cached_at: float = 0


def _analyze_sectors() -> dict:
    """Analyze all sectors and generate 30-day recommendations."""
    vix_df = _fetcher.get_daily_ohlcv("^VIX", period="1y", live=True)
    spy_df = _fetcher.get_daily_ohlcv("SPY", period="1y", live=True)
    regime_result = detect_regime(vix_df, spy_df)
    regime = regime_result["regime"].value
    vol = compute_vol_context(spy_df, vix_df)

    sectors: list[dict] = []

    for name, etf in SECTOR_ETFS.items():
        try:
            df = _fetcher.get_daily_ohlcv(etf, period="6mo", live=True)
            if df.empty or len(df) < 60:
                continue

            close = df["Close"]
            price = float(close.iloc[-1])

            ret_5d = float((close.iloc[-1] / close.iloc[-5] - 1) * 100) if len(close) >= 5 else 0
            ret_20d = float((close.iloc[-1] / close.iloc[-20] - 1) * 100) if len(close) >= 20 else 0
            ret_60d = float((close.iloc[-1] / close.iloc[-60] - 1) * 100) if len(close) >= 60 else 0

            delta = close.diff()
            gain = delta.where(delta > 0, 0).tail(14).mean()
            loss = (-delta.where(delta < 0, 0)).tail(14).mean()
            rs = gain / loss if loss > 0 else 100
            rsi = float(100 - (100 / (1 + rs)))

            sma_50 = float(close.tail(50).mean())
            sma_200 = float(close.tail(200).mean()) if len(close) >= 200 else sma_50

            # Sector score: momentum + mean-reversion + trend
            score = 50.0
            if rsi < 30:
                score += 20  # oversold bounce
            elif rsi < 40:
                score += 10
            elif rsi > 70:
                score -= 10
            elif rsi > 80:
                score -= 20

            if ret_20d > 3:
                score += 10
            elif ret_20d < -5:
                score += 5  # contrarian bounce potential

            if price > sma_50 > sma_200:
                score += 15  # uptrend
            elif price > sma_200:
                score += 5
            elif price < sma_200:
                score -= 10

            if ret_60d > 10:
                score += 5
            if ret_60d < -10:
                score -= 5

            # Regime adjustments
            if "bear" in regime or "crisis" in regime:
                if name in ("utilities", "consumer_staples", "healthcare"):
                    score += 10  # defensive sectors favored
                elif name in ("technology", "consumer_discretionary"):
                    score -= 10  # cyclicals penalized

            score = max(0, min(100, score))

            if score >= 65:
                verdict = "BUY"
            elif score >= 50:
                verdict = "HOLD"
            elif score >= 35:
                verdict = "REDUCE"
            else:
                verdict = "AVOID"

            # Long-term outlook (6-12 months)
            if price > sma_200 and ret_60d > 5 and rsi < 65:
                lt_outlook = "Bullish — uptrend intact, room to run"
            elif price > sma_200 and rsi > 70:
                lt_outlook = "Caution — uptrend but overbought, expect a pullback before more upside"
            elif price > sma_200 and rsi < 35:
                lt_outlook = "Strong buy — uptrend with deep pullback, best entry window"
            elif price < sma_200 and rsi < 30:
                lt_outlook = "Contrarian buy — beaten down, watch for reversal confirmation"
            elif price < sma_200:
                lt_outlook = "Bearish — below long-term trend, wait for recovery"
            else:
                lt_outlook = "Neutral — no strong directional view"

            sectors.append({
                "sector": name.replace("_", " ").title(),
                "etf": etf,
                "price": round(price, 2),
                "return_5d": round(ret_5d, 1),
                "return_20d": round(ret_20d, 1),
                "return_60d": round(ret_60d, 1),
                "rsi": round(rsi, 1),
                "score": round(score),
                "verdict": verdict,
                "long_term_outlook": lt_outlook,
            })

        except Exception as e:
            logger.debug("Sector %s analysis failed: %s", name, e)

    sectors.sort(key=lambda s: s["score"], reverse=True)

    # Pick top stocks from BUY and HOLD sectors
    investable = [s for s in sectors if s["verdict"] in ("BUY", "HOLD")]
    stock_picks = _pick_stocks_from_sectors(investable)

    return {
        "regime": regime,
        "vix": round(vol.vix_current, 1),
        "sectors": sectors,
        "top_sectors": [s["sector"] for s in sectors if s["verdict"] == "BUY"],
        "avoid_sectors": [s["sector"] for s in sectors if s["verdict"] in ("AVOID", "REDUCE")],
        "stock_picks": stock_picks,
    }


def _score_one_stock(ticker: str, sector_display: str, name: str) -> dict | None:
    """Score a single stock for sector-based picking. Returns dict or None."""
    try:
        df = _fetcher.get_daily_ohlcv(ticker, period="3mo", live=True)
        if df.empty or len(df) < 20:
            return None

        close = df["Close"]
        price = float(close.iloc[-1])
        ret_20d = float((close.iloc[-1] / close.iloc[-20] - 1) * 100)

        delta = close.diff()
        gain = delta.where(delta > 0, 0).tail(14).mean()
        loss = (-delta.where(delta < 0, 0)).tail(14).mean()
        rs = gain / loss if loss > 0 else 100
        rsi = float(100 - (100 / (1 + rs)))

        sma_50 = float(close.tail(50).mean()) if len(close) >= 50 else price
        sma_200 = float(close.tail(200).mean()) if len(close) >= 200 else price

        high = df["High"]
        low = df["Low"]
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        atr = float(tr.tail(14).mean())

        entry = round(min(price, sma_50 * 0.99) if price > sma_50 else price, 2)
        stop_loss = round(entry - atr * 2, 2)
        target_30 = round(entry * 1.30, 2)

        stock_score = 50.0
        if rsi < 35:
            stock_score += 20
        elif rsi < 45:
            stock_score += 10
        elif rsi > 75:
            stock_score -= 15

        if price > sma_50:
            stock_score += 10

        if -8 < ret_20d < -2:
            stock_score += 10

        stock_score = max(0, min(100, stock_score))

        return {
            "ticker": ticker,
            "name": name,
            "sector": sector_display,
            "price": round(price, 2),
            "entry": entry,
            "stop_loss": stop_loss,
            "target": target_30,
            "analyst_target": None,
            "atr": round(atr, 2),
            "sma_200": round(sma_200, 2),
            "return_20d": round(ret_20d, 1),
            "rsi": round(rsi, 1),
            "score": round(stock_score),
            "why": _stock_reason(rsi, ret_20d, price, sma_50),
        }
    except Exception:
        return None


def _pick_stocks_from_sectors(top_sectors: list[dict]) -> list[dict]:
    """Pick the best stocks from the favored sectors using parallel analysis."""
    picks: list[dict] = []

    try:
        universe = fetch_sp500_constituents()
    except Exception:
        return picks

    if universe.empty or "sector" not in universe.columns:
        return picks

    sector_name_map = {
        "Technology": "Information Technology",
        "Financials": "Financials",
        "Energy": "Energy",
        "Healthcare": "Health Care",
        "Consumer Discretionary": "Consumer Discretionary",
        "Consumer Staples": "Consumer Staples",
        "Industrials": "Industrials",
        "Materials": "Materials",
        "Utilities": "Utilities",
        "Real Estate": "Real Estate",
        "Communication": "Communication Services",
    }

    # Build a flat list of (ticker, sector, name) tuples across all sectors
    tasks: list[tuple[str, str, str]] = []
    for sector_info in top_sectors:
        sector_display = sector_info["sector"]
        gics_sector = sector_name_map.get(sector_display, sector_display)

        sector_stocks = universe[universe["sector"] == gics_sector]
        if sector_stocks.empty:
            continue

        tickers = sector_stocks["ticker"].tolist()[:12]
        for ticker in tickers:
            name = (
                sector_stocks[sector_stocks["ticker"] == ticker]["name"].iloc[0]
                if "name" in sector_stocks.columns else ticker
            )
            tasks.append((ticker, sector_display, name))

    # Score all tickers in parallel
    with ThreadPoolExecutor(max_workers=15) as pool:
        results = pool.map(lambda t: _score_one_stock(*t), tasks)

    # Collect all scored candidates
    all_scored: list[dict] = [r for r in results if r is not None]
    all_scored.sort(key=lambda s: s["score"], reverse=True)

    if not all_scored:
        return picks

    # Ask AI to pick the best 5 from all candidates
    try:
        from backend.ai.market_ai import ai_pick_dashboard_stocks
        from backend.regime.detector import detect_regime as _detect

        vix_df = _fetcher.get_daily_ohlcv("^VIX", period="3mo", live=True)
        spy_df = _fetcher.get_daily_ohlcv("SPY", period="1y", live=True)
        regime_result = _detect(vix_df, spy_df)
        regime_str = regime_result.get("regime", "unknown")
        if hasattr(regime_str, "value"):
            regime_str = regime_str.value

        ai_result = ai_pick_dashboard_stocks(regime_str, all_scored)
        if ai_result:
            ai_tickers, ai_reasons = ai_result
            ticker_map = {s["ticker"]: s for s in all_scored}
            for ticker in ai_tickers:
                if ticker in ticker_map:
                    pick = ticker_map[ticker]
                    if ai_reasons.get(ticker):
                        pick["why"] = ai_reasons[ticker]
                    picks.append(pick)
            if picks:
                logger.info("AI picked %d dashboard stocks", len(picks))
                return picks
    except Exception as e:
        logger.warning("AI stock picker failed, falling back to score-based: %s", e)

    # Fallback: top 3 per sector by score
    sector_buckets: dict[str, list[dict]] = {}
    for s in all_scored:
        sector = s["sector"]
        if sector not in sector_buckets:
            sector_buckets[sector] = []
        sector_buckets[sector].append(s)

    for sector_list in sector_buckets.values():
        picks.extend(sector_list[:TOP_PICKS_PER_SECTOR])

    picks.sort(key=lambda s: s["score"], reverse=True)
    return picks


def _stock_reason(rsi: float, ret_20d: float, price: float, sma_50: float) -> str:
    parts = []
    if rsi < 35:
        parts.append(f"oversold (RSI {rsi:.0f})")
    if -8 < ret_20d < -2:
        parts.append(f"pullback ({ret_20d:+.1f}% this month)")
    if price > sma_50:
        parts.append("above 50-SMA")
    if not parts:
        if rsi < 50:
            parts.append(f"RSI neutral ({rsi:.0f})")
        else:
            parts.append(f"momentum (RSI {rsi:.0f})")
    return ", ".join(parts).capitalize()


@router.get("/recommendations")
async def get_sector_recommendations(
    refresh: bool = Query(False, description="Force fresh analysis, bypass cache"),
) -> dict:
    """30-day sector and stock recommendations based on current market regime."""
    global _cached_result, _cached_at

    if not refresh and _cached_result and (time.time() - _cached_at) < _CACHE_TTL_SECONDS:
        age_min = (time.time() - _cached_at) / 60
        logger.info("Returning cached recommendations (%.0f min old)", age_min)
        return {**_cached_result, "cached": True, "cache_age_minutes": round(age_min, 1)}

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, _analyze_sectors)
    _cached_result = result
    _cached_at = time.time()
    return {**result, "cached": False, "cache_age_minutes": 0}

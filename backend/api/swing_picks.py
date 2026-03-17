"""Swing Picks — aggressive 30%+ return scanner for 1-10 day holds.

Dynamically discovers volatile stocks from:
  1. S&P 500 universe (filtered by ATR% > threshold)
  2. yfinance market movers (top gainers, losers, most active — naturally volatile today)
  3. Finnhub company news tickers (stocks in the news = potential catalysts)

No hardcoded watchlists — everything is discovered fresh on each scan.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from fastapi import APIRouter, Query

from backend.data.fetcher import DataFetcher
from backend.data.sources.yfinance_src import yfinance_source

router = APIRouter(prefix="/swing", tags=["swing_picks"])
logger = logging.getLogger(__name__)
_fetcher = DataFetcher()
_executor = ThreadPoolExecutor(max_workers=3)


def _get_yfinance_movers() -> list[str]:
    """Fetch today's most active / top gainers / top losers from yfinance."""
    tickers: set[str] = set()
    try:
        import yfinance as yf
        for screener_key in ("most_actives", "day_gainers", "day_losers"):
            try:
                s = yf.screen(screener_key)
                if s and "quotes" in s:
                    for q in s["quotes"][:30]:
                        sym = q.get("symbol", "")
                        if sym and "." not in sym and len(sym) <= 5:
                            tickers.add(sym)
            except Exception:
                pass
        logger.info("yfinance movers: found %d tickers", len(tickers))
    except Exception:
        logger.debug("yfinance screener unavailable")
    return list(tickers)


def _get_finnhub_news_tickers() -> list[str]:
    """Extract tickers from Finnhub general market news."""
    tickers: set[str] = set()
    try:
        from backend.config import settings
        if not settings.finnhub_api_key:
            return []
        from backend.data.sources.finnhub_src import finnhub_source
        data = finnhub_source._get(
            "/news", params={"category": "general", "minId": "0"}
        )
        if isinstance(data, list):
            for article in data[:50]:
                related = article.get("related", "")
                if related:
                    for sym in related.split(","):
                        sym = sym.strip().upper()
                        if sym and 1 <= len(sym) <= 5 and sym.isalpha():
                            tickers.add(sym)
            logger.info("Finnhub news tickers: found %d", len(tickers))
    except Exception:
        logger.debug("Finnhub news ticker extraction failed")
    return list(tickers)


def _get_scan_universe() -> list[str]:
    """Build dynamic scan universe — no hardcoded lists.

    Sources:
      1. S&P 500 constituents (always available via Wikipedia cache)
      2. yfinance market movers (today's most active, gainers, losers)
      3. Finnhub news tickers (stocks in the headlines)

    All tickers are deduplicated. Delisted/invalid tickers are skipped
    gracefully during the scan phase.
    """
    tickers: set[str] = set()

    # S&P 500 universe
    try:
        from backend.data.universe import get_all_tickers
        sp500 = get_all_tickers()
        tickers.update(sp500)
        logger.info("Universe: %d S&P 500 tickers", len(sp500))
    except Exception:
        logger.debug("Failed to load S&P 500 universe")

    # Today's market movers (dynamic — changes every day)
    movers = _get_yfinance_movers()
    tickers.update(movers)

    # Tickers in the news (dynamic — catalyst-driven)
    news_tickers = _get_finnhub_news_tickers()
    tickers.update(news_tickers)

    logger.info("Total scan universe: %d unique tickers", len(tickers))
    return list(tickers)


def _analyze_ticker_for_swing(ticker: str, max_hold_days: int, min_return_pct: float) -> dict | None:
    """Analyze a single ticker for swing trade potential."""
    try:
        df = yfinance_source.get_daily_ohlcv(ticker, period="3mo")
        if df.empty or len(df) < 20:
            return None

        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        volume = df["Volume"]
        price = float(close.iloc[-1])

        if price < 1.0 or price > 10000:
            return None

        # ATR (14-period)
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        atr = float(tr.tail(14).mean())
        atr_pct = atr / price * 100 if price > 0 else 0

        if atr_pct < 2.0:
            return None

        # Can this stock plausibly move min_return_pct% in max_hold_days?
        # Assume favorable trend captures ~60% of daily ATR as directional gain
        projected_return = atr_pct * 0.6 * max_hold_days
        if projected_return < min_return_pct:
            return None

        # Momentum signals
        ret_1d = float((close.iloc[-1] / close.iloc[-2] - 1) * 100) if len(close) >= 2 else 0
        ret_5d = float((close.iloc[-1] / close.iloc[-5] - 1) * 100) if len(close) >= 5 else 0
        ret_20d = float((close.iloc[-1] / close.iloc[-20] - 1) * 100) if len(close) >= 20 else 0

        # Volume surge
        avg_vol_20d = float(volume.tail(20).mean())
        latest_vol = float(volume.iloc[-1])
        vol_ratio = latest_vol / avg_vol_20d if avg_vol_20d > 0 else 1.0

        # RSI
        delta = close.diff()
        gain = delta.where(delta > 0, 0).tail(14).mean()
        loss = (-delta.where(delta < 0, 0)).tail(14).mean()
        rs = gain / loss if loss > 0 else 100
        rsi = float(100 - (100 / (1 + rs)))

        # SMAs
        sma_20 = float(close.tail(20).mean())
        sma_50 = float(close.tail(50).mean()) if len(close) >= 50 else sma_20

        # 20d support/resistance
        support_20d = float(df.tail(20)["Low"].min())
        resistance_20d = float(df.tail(20)["High"].max())

        # Distance from 20d low (how much room to drop)
        dist_from_low = (price - support_20d) / price * 100

        # Determine direction and calculate targets
        # Bullish: momentum up, RSI not overbought, volume confirmation
        # Bearish short: broken trend, high RSI, rejection from resistance
        direction = "long"
        if ret_5d < -5 and rsi < 35 and price < sma_20:
            direction = "long"  # oversold bounce play
            catalyst_type = "Oversold bounce"
        elif ret_5d > 5 and vol_ratio > 1.5:
            direction = "long"  # momentum continuation
            catalyst_type = "Momentum breakout"
        elif rsi < 30:
            direction = "long"
            catalyst_type = "RSI oversold reversal"
        elif ret_1d > 3 and vol_ratio > 2:
            direction = "long"  # gap-up continuation
            catalyst_type = "Volume surge"
        elif vol_ratio > 3:
            direction = "long"
            catalyst_type = "Extreme volume spike"
        else:
            catalyst_type = "High ATR setup"

        # Entry, stop, target
        entry = round(price, 2)

        if direction == "long":
            stop = round(price - atr * 2, 2)
            target = round(price * (1 + min_return_pct / 100), 2)
        else:
            stop = round(price + atr * 2, 2)
            target = round(price * (1 - min_return_pct / 100), 2)

        stop_pct = abs(entry - stop) / entry * 100
        target_return = abs(target - entry) / entry * 100
        rr_ratio = target_return / stop_pct if stop_pct > 0 else 0

        # Determine hold bucket: quick (1-3d) or swing (3-10d)
        days_needed = max(1, int(min_return_pct / (atr_pct * 0.6)))
        if days_needed <= 3:
            hold_bucket = "quick"
            hold_label = f"1-3 days"
        else:
            hold_bucket = "swing"
            hold_label = f"{min(days_needed, 3)}-{min(days_needed + 3, max_hold_days)} days"

        # Exit window (specific dates)
        exit_by_date = (date.today() + timedelta(days=days_needed + 2)).strftime("%a %b %d")
        exit_window = f"Sell by {exit_by_date} or when target hit"

        # Scoring: combine momentum, volume, ATR feasibility, RSI setup
        score = 0.0
        score += min(25, projected_return / min_return_pct * 15)  # feasibility
        if vol_ratio > 2:
            score += 20
        elif vol_ratio > 1.5:
            score += 10
        if 25 < rsi < 40:
            score += 15  # oversold bounce setup
        elif ret_5d > 8:
            score += 15  # strong momentum
        if rr_ratio > 2:
            score += 15
        elif rr_ratio > 1.5:
            score += 10
        if ret_1d > 2:
            score += 10  # today's momentum
        score = min(100, score)

        if score < 30:
            return None

        # Risk assessment
        if atr_pct > 8:
            risk = "EXTREME"
        elif atr_pct > 5:
            risk = "VERY HIGH"
        else:
            risk = "HIGH"

        # Check for insider buying as bonus signal
        insider_note = ""
        try:
            insider = _fetcher.get_insider_buying_score(ticker)
            if insider.get("signal_score", 0) > 30:
                insider_note = f" + Insider buying (score {insider['signal_score']:.0f})"
                score = min(100, score + 10)
        except Exception:
            pass

        # Build short plain-English analysis
        analysis = _build_swing_summary(
            ticker, price, ret_1d, ret_5d, ret_20d, rsi, atr_pct,
            vol_ratio, catalyst_type, direction, target, stop,
            hold_label, days_needed,
        )

        return {
            "ticker": ticker,
            "price": price,
            "direction": direction,
            "entry": entry,
            "stop": stop,
            "stop_pct": round(stop_pct, 1),
            "target": target,
            "return_pct": round(target_return, 1),
            "risk_reward": round(rr_ratio, 1),
            "hold_bucket": hold_bucket,
            "hold_days": hold_label,
            "exit_window": exit_window,
            "atr_pct": round(atr_pct, 1),
            "rsi": round(rsi, 0),
            "volume_ratio": round(vol_ratio, 1),
            "ret_1d": round(ret_1d, 1),
            "ret_5d": round(ret_5d, 1),
            "catalyst": catalyst_type + insider_note,
            "risk_level": risk,
            "score": round(score, 0),
            "analysis": analysis,
        }
    except Exception:
        return None


def _build_swing_summary(
    ticker: str, price: float, ret_1d: float, ret_5d: float, ret_20d: float,
    rsi: float, atr_pct: float, vol_ratio: float, catalyst: str,
    direction: str, target: float, stop: float, hold_label: str, days_needed: int,
) -> str:
    """Short plain-English analysis for a swing pick."""
    parts: list[str] = []

    # What's happening
    if ret_1d > 3:
        parts.append(f"{ticker} is surging today (+{ret_1d:.1f}%) with {vol_ratio:.1f}x normal volume.")
    elif ret_1d > 0.5:
        parts.append(f"{ticker} is up {ret_1d:+.1f}% today.")
    elif ret_1d < -3:
        parts.append(f"{ticker} is selling off today ({ret_1d:+.1f}%).")
    else:
        parts.append(f"{ticker} is roughly flat today.")

    # Why this setup
    if "Oversold bounce" in catalyst:
        parts.append(f"It's down {ret_5d:+.1f}% this week and RSI is at {rsi:.0f} — oversold. Historically, stocks this oversold bounce within 3-5 days.")
    elif "Momentum breakout" in catalyst:
        parts.append(f"It's up {ret_5d:+.1f}% this week on heavy volume — momentum is building and likely continues.")
    elif "Volume surge" in catalyst:
        parts.append(f"Volume is {vol_ratio:.1f}x average — big players are moving in. When volume spikes like this, the move usually has legs.")
    elif "RSI oversold" in catalyst:
        parts.append(f"RSI at {rsi:.0f} is deeply oversold. This stock moves {atr_pct:.1f}% per day on average — a bounce could be sharp.")
    else:
        parts.append(f"This stock moves {atr_pct:.1f}% per day on average — enough volatility for a big swing.")

    # The trade
    gain_pct = abs(target - price) / price * 100
    loss_pct = abs(stop - price) / price * 100
    parts.append(
        f"Buy at ${price:.2f}, target ${target:.2f} (+{gain_pct:.0f}%), stop at ${stop:.2f} (-{loss_pct:.0f}%). "
        f"Hold for {hold_label}."
    )

    # Risk warning
    if atr_pct > 6:
        parts.append("This is an extremely volatile stock — it can move 5-10% in a single day. Size very small (1% of capital max).")
    else:
        parts.append("This is a high-risk trade. Don't bet more than 1-2% of your capital.")

    # If you need capital
    parts.append(
        f"If you need the capital sooner, sell if you're up 10-15% — don't wait for the full target. "
        f"If it goes against you and hits ${stop:.2f}, exit immediately — no hoping."
    )

    return " ".join(parts)


def _run_swing_scan(min_return_pct: float, max_hold_days: int) -> dict:
    """Scan the full universe for swing picks (runs in thread pool)."""
    universe = _get_scan_universe()
    logger.info("Swing scan: scanning %d tickers for %.0f%%+ in %dd...", len(universe), min_return_pct, max_hold_days)

    quick_trades: list[dict] = []
    swing_trades: list[dict] = []
    scanned = 0

    for ticker in universe:
        result = _analyze_ticker_for_swing(ticker, max_hold_days, min_return_pct)
        scanned += 1
        if result is None:
            continue

        if result["hold_bucket"] == "quick":
            quick_trades.append(result)
        else:
            swing_trades.append(result)

    quick_trades.sort(key=lambda x: x["score"], reverse=True)
    swing_trades.sort(key=lambda x: x["score"], reverse=True)

    quick_trades = quick_trades[:15]
    swing_trades = swing_trades[:15]

    logger.info(
        "Swing scan complete: %d quick + %d swing picks from %d tickers",
        len(quick_trades), len(swing_trades), scanned,
    )

    return {
        "quick_trades": quick_trades,
        "swing_trades": swing_trades,
        "scan_stats": {
            "tickers_scanned": scanned,
            "timestamp": datetime.utcnow().isoformat(),
            "min_return_target": min_return_pct,
            "max_hold_days": max_hold_days,
        },
    }


# Background scan state (in-memory, single-worker safe)
_scan_state: dict = {
    "status": "idle",     # idle | scanning | done | error
    "progress": 0,        # tickers scanned so far
    "total": 0,           # total tickers to scan
    "result": None,       # scan results when done
    "started_at": None,
    "error": None,
}


def _run_scan_background(min_return_pct: float, max_hold_days: int) -> None:
    """Run scan and store results in _scan_state (called from thread pool)."""
    global _scan_state
    try:
        _scan_state["status"] = "scanning"
        _scan_state["started_at"] = datetime.utcnow().isoformat()
        _scan_state["error"] = None

        universe = _get_scan_universe()
        _scan_state["total"] = len(universe)
        logger.info("Background swing scan: %d tickers, %.0f%%+ in %dd",
                     len(universe), min_return_pct, max_hold_days)

        quick_trades: list[dict] = []
        swing_trades: list[dict] = []

        for i, ticker in enumerate(universe):
            _scan_state["progress"] = i + 1
            result = _analyze_ticker_for_swing(ticker, max_hold_days, min_return_pct)
            if result is not None:
                if result["hold_bucket"] == "quick":
                    quick_trades.append(result)
                else:
                    swing_trades.append(result)

        quick_trades.sort(key=lambda x: x["score"], reverse=True)
        swing_trades.sort(key=lambda x: x["score"], reverse=True)

        _scan_state["result"] = {
            "quick_trades": quick_trades[:15],
            "swing_trades": swing_trades[:15],
            "scan_stats": {
                "tickers_scanned": len(universe),
                "timestamp": datetime.utcnow().isoformat(),
                "min_return_target": min_return_pct,
                "max_hold_days": max_hold_days,
            },
        }
        _scan_state["status"] = "done"
        logger.info("Background swing scan done: %d quick + %d swing",
                     len(quick_trades[:15]), len(swing_trades[:15]))
    except Exception as e:
        _scan_state["status"] = "error"
        _scan_state["error"] = str(e)
        logger.exception("Background swing scan failed")


@router.post("/start-scan")
async def start_swing_scan(
    min_return_pct: float = Query(default=30.0, ge=5.0, le=100.0),
    max_hold_days: int = Query(default=10, ge=1, le=30),
) -> dict:
    """Kick off a swing scan in the background. Returns immediately."""
    if _scan_state["status"] == "scanning":
        return {
            "status": "already_scanning",
            "progress": _scan_state["progress"],
            "total": _scan_state["total"],
        }

    _scan_state["status"] = "scanning"
    _scan_state["progress"] = 0
    _scan_state["total"] = 0
    _scan_state["result"] = None

    _executor.submit(_run_scan_background, min_return_pct, max_hold_days)
    return {"status": "started"}


@router.get("/status")
async def get_scan_status() -> dict:
    """Poll scan progress. Returns status, progress, and results when done."""
    return {
        "status": _scan_state["status"],
        "progress": _scan_state["progress"],
        "total": _scan_state["total"],
        "result": _scan_state["result"] if _scan_state["status"] == "done" else None,
        "error": _scan_state["error"],
    }


@router.get("/picks")
async def get_swing_picks(
    min_return_pct: float = Query(default=30.0, ge=5.0, le=100.0, description="Minimum target return %"),
    max_hold_days: int = Query(default=10, ge=1, le=30, description="Maximum hold period in days"),
) -> dict:
    """Synchronous scan (blocks until done). Use /start-scan + /status for async."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, _run_swing_scan, min_return_pct, max_hold_days)
    return result

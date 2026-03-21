"""Swing Picks — aggressive 30%+ return scanner for 1-10 day holds.

Dynamically discovers volatile stocks from:
  1. S&P 500 universe (filtered by ATR% > threshold)
  2. yfinance market movers (top gainers, losers, most active — naturally volatile today)
  3. Finnhub company news tickers (stocks in the news = potential catalysts)

No hardcoded watchlists — everything is discovered fresh on each scan.
Every pick is auto-logged to the signal audit / shadow book.
AI analysis is generated server-side so the frontend receives complete results.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from datetime import UTC, date, datetime, timedelta

import pandas as pd
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from backend.ai.market_ai import ai_swing_summary
from backend.data.cache import data_cache
from backend.data.fetcher import DataFetcher
from backend.data.sentiment_cache import sentiment_cache
from backend.tracker.signal_audit import SignalAuditor

router = APIRouter(prefix="/swing", tags=["swing_picks"])
logger = logging.getLogger(__name__)
_fetcher = DataFetcher()
_executor = ThreadPoolExecutor(max_workers=3)
_auditor = SignalAuditor()
_scan_lock = threading.Lock()


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

        data = finnhub_source._get("/news", params={"category": "general", "minId": "0"})
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

    Sources (fetched in parallel):
      1. S&P 500 constituents (always available via Wikipedia cache)
      2. yfinance market movers (today's most active, gainers, losers)
      3. Finnhub news tickers (stocks in the headlines)
    """
    tickers: set[str] = set()

    try:
        from backend.data.universe import get_all_tickers

        sp500 = get_all_tickers()
        tickers.update(sp500)
        logger.info("Universe: %d S&P 500 tickers", len(sp500))
    except Exception:
        logger.debug("Failed to load S&P 500 universe")

    with ThreadPoolExecutor(max_workers=2) as pool:
        movers_future = pool.submit(_get_yfinance_movers)
        news_future = pool.submit(_get_finnhub_news_tickers)
        try:
            tickers.update(movers_future.result(timeout=30))
        except (TimeoutError, Exception):
            logger.warning("yfinance movers timed out")
        try:
            tickers.update(news_future.result(timeout=30))
        except (TimeoutError, Exception):
            logger.warning("Finnhub news tickers timed out")

    logger.info("Total scan universe: %d unique tickers", len(tickers))
    return list(tickers)


def _fetch_fundamentals(ticker: str) -> dict:
    """Grab key fundamentals for a swing pick via yfinance. Fast, best-effort."""
    try:
        import yfinance as yf

        info = yf.Ticker(ticker).info or {}
        return {
            "name": info.get("shortName") or info.get("longName") or ticker,
            "sector": info.get("sector", "Unknown"),
            "industry": info.get("industry", "Unknown"),
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "revenue_growth": info.get("revenueGrowth"),
            "analyst_target": info.get("targetMeanPrice"),
        }
    except Exception:
        return {"name": ticker, "sector": "Unknown"}


def _check_earnings_soon(ticker: str, hold_days: int) -> bool:
    """Return True if earnings fall within hold_days + 2 trading days."""
    try:
        import yfinance as yf

        cal = yf.Ticker(ticker).calendar
        if cal is None:
            return False
        # yfinance returns a dict with 'Earnings Date' as a list of Timestamps
        dates = cal.get("Earnings Date", [])
        if not dates:
            return False
        cutoff = date.today() + timedelta(days=hold_days + 4)
        for d in dates:
            if hasattr(d, "date"):
                d = d.date()
            if date.today() <= d <= cutoff:
                return True
    except Exception:
        pass
    return False


def _analyze_ticker_for_swing(
    ticker: str,
    max_hold_days: int,
    min_return_pct: float,
    regime: str = "unknown",
    pre_fetched_ohlcv: pd.DataFrame | None = None,
) -> dict | None:
    """Analyze a single ticker for swing trade potential."""
    try:
        df = (
            pre_fetched_ohlcv
            if pre_fetched_ohlcv is not None
            else _fetcher.get_daily_ohlcv(ticker, period="3mo", live=False)
        )
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
        tr = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
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
            direction = "long"
            catalyst_type = "Beaten down, due for a bounce"
        elif ret_5d > 5 and vol_ratio > 1.5:
            direction = "long"
            catalyst_type = "Climbing fast with heavy buying"
        elif rsi < 30:
            direction = "long"
            catalyst_type = "Stock dropped hard, likely to recover"
        elif ret_1d > 3 and vol_ratio > 2:
            direction = "long"
            catalyst_type = "Big jump today on heavy trading"
        elif vol_ratio > 3:
            direction = "long"
            catalyst_type = "Unusual amount of trading activity"
        else:
            catalyst_type = "Big daily price swings"

        # Entry, stop, target
        entry = round(price, 2)

        # Target based on each stock's actual ATR volatility, not a flat %
        realistic_return = min(projected_return, 150.0)
        realistic_return = max(realistic_return, min_return_pct)

        if direction == "long":
            stop = round(max(price * 0.80, price - atr * 2), 2)
            atr_target = round(price * (1 + realistic_return / 100), 2)
            res_target = round(resistance_20d * 1.02, 2) if resistance_20d > price else atr_target
            target = round(max(atr_target, res_target), 2)
        else:
            stop = round(min(price * 1.20, price + atr * 2), 2)
            target = round(price * (1 - realistic_return / 100), 2)

        stop_pct = abs(entry - stop) / entry * 100
        target_return = abs(target - entry) / entry * 100
        rr_ratio = target_return / stop_pct if stop_pct > 0 else 0

        # Determine hold bucket: quick (1-3d) or swing (3-10d)
        days_needed = max(1, int(min_return_pct / (atr_pct * 0.6)))
        if days_needed <= 3:
            hold_bucket = "quick"
            hold_days_num = days_needed
        else:
            hold_bucket = "swing"
            hold_days_num = min(days_needed + 2, max_hold_days)
        hold_label = f"{hold_days_num} days"

        # Exit window (specific dates)
        exit_by_date = (date.today() + timedelta(days=days_needed + 2)).strftime("%a %b %d")
        exit_window = f"Sell by {exit_by_date} or when target hit"

        # Scoring: feasibility + quality of setup + momentum confirmation
        score = 0.0

        # Feasibility: can the stock actually move this much? (ATR projection)
        score += min(20, projected_return / min_return_pct * 12)

        # Risk/reward quality (most important for swing trades)
        if rr_ratio > 3:
            score += 20
        elif rr_ratio > 2:
            score += 15
        elif rr_ratio > 1.5:
            score += 10

        # Volume confirmation
        if vol_ratio > 2:
            score += 15
        elif vol_ratio > 1.5:
            score += 10
        elif vol_ratio > 1.2:
            score += 5

        # Setup quality: RSI + trend alignment
        if 25 < rsi < 40:
            score += 12  # oversold bounce — high-quality entry
        elif 40 <= rsi < 60:
            score += 8  # neutral RSI — room to run
        elif ret_5d > 8:
            score += 10  # strong momentum

        # Trend alignment: price above key MAs is bullish
        if direction == "long":
            if price > sma_50:
                score += 8
            if price > sma_20:
                score += 5

        # Proximity to support (buying near support = better entry)
        if direction == "long" and dist_from_low < 5:
            score += 8

        # Today's momentum confirmation
        if ret_1d > 2:
            score += 7

        # Regime-aware adjustments
        regime_lower = regime.lower()
        if "crisis" in regime_lower or "bear" in regime_lower:
            if rsi < 35:
                score += 5
            if ret_5d > 5:
                score -= 5
        elif "bull" in regime_lower:
            if ret_5d > 5 and vol_ratio > 1.5:
                score += 5

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
                insider_note = " + Insider buying"
                score = min(100, score + 10)
        except Exception:
            pass

        # FinBERT sentiment scoring — impact scales with sentiment extremity
        # and adapts to current regime (trend-confirming sentiment worth more)
        sentiment_score: float | None = None
        sentiment_label: str | None = None
        sentiment_note = ""
        cached_sent = sentiment_cache.get(ticker)
        if cached_sent is not None:
            sentiment_score = cached_sent.composite_score
            sentiment_label = cached_sent.sentiment_label
            extremity = abs(cached_sent.composite_score - 50) / 50.0  # 0.0–1.0

            if direction == "long":
                if cached_sent.sentiment_label == "bullish":
                    boost = 6 + extremity * 10  # 6–16 range
                    if "bull" in regime_lower:
                        boost *= 1.15  # confirming sentiment worth more in bull trend
                    score = min(100, score + round(boost))
                    sentiment_note = " + Bullish news sentiment"
                elif cached_sent.sentiment_label == "bearish":
                    penalty = 4 + extremity * 8  # 4–12 range
                    if "crisis" in regime_lower or "bear" in regime_lower:
                        penalty *= 0.6  # contrarian buys penalized less in bear mkt
                    score = max(0, score - round(penalty))
                    sentiment_note = " + Bearish news (contrarian)"
            else:
                if cached_sent.sentiment_label == "bearish":
                    boost = 6 + extremity * 10
                    score = min(100, score + round(boost))
                    sentiment_note = " + Bearish news confirms short"

        # Fetch fundamentals (name, sector, P/E, analyst target)
        fund = _fetch_fundamentals(ticker)

        # Earnings check — flag picks with earnings during the hold period
        earnings_soon = _check_earnings_soon(ticker, hold_days_num)
        earnings_warning = ""
        if earnings_soon:
            earnings_warning = "Earnings during hold period"
            score = max(0, score - 10)

        # Build short plain-English analysis
        analysis = _build_swing_summary(
            ticker,
            price,
            ret_1d,
            ret_5d,
            ret_20d,
            rsi,
            atr_pct,
            vol_ratio,
            catalyst_type,
            direction,
            target,
            stop,
            hold_label,
            days_needed,
            sentiment_score=sentiment_score,
            sentiment_label=sentiment_label,
        )

        result_dict: dict = {
            "ticker": ticker,
            "name": fund.get("name", ticker),
            "sector": fund.get("sector", "Unknown"),
            "industry": fund.get("industry", "Unknown"),
            "market_cap": fund.get("market_cap"),
            "pe_ratio": fund.get("pe_ratio"),
            "analyst_target": fund.get("analyst_target"),
            "price": round(price, 2),
            "direction": direction,
            "entry": entry,
            "stop": stop,
            "stop_pct": round(stop_pct, 1),
            "target": target,
            "return_pct": round(target_return, 1),
            "risk_reward": round(rr_ratio, 1),
            "hold_bucket": hold_bucket,
            "hold_days": hold_days_num,
            "hold_label": hold_label,
            "exit_window": exit_window,
            "atr_pct": round(atr_pct, 1),
            "rsi": round(rsi, 0),
            "volume_ratio": round(vol_ratio, 1),
            "ret_1d": round(ret_1d, 1),
            "ret_5d": round(ret_5d, 1),
            "catalyst": catalyst_type + insider_note + sentiment_note,
            "risk_level": risk,
            "score": round(score, 0),
            "analysis": analysis,
            "earnings_warning": earnings_warning,
        }
        if sentiment_score is not None:
            result_dict["sentiment_score"] = round(sentiment_score, 1)
            result_dict["sentiment_label"] = sentiment_label
        return result_dict
    except Exception:
        return None


def _build_swing_summary(
    ticker: str,
    price: float,
    ret_1d: float,
    ret_5d: float,
    ret_20d: float,
    rsi: float,
    atr_pct: float,
    vol_ratio: float,
    catalyst: str,
    direction: str,
    target: float,
    stop: float,
    hold_label: str,
    days_needed: int,
    sentiment_score: float | None = None,
    sentiment_label: str | None = None,
) -> str:
    """Plain-English analysis for a swing pick — zero finance jargon."""
    parts: list[str] = []

    if ret_1d > 3:
        parts.append(f"{ticker} jumped {ret_1d:.1f}% today with way more trading activity than usual.")
    elif ret_1d > 0.5:
        parts.append(f"{ticker} is up slightly today ({ret_1d:+.1f}%).")
    elif ret_1d < -3:
        parts.append(f"{ticker} dropped {abs(ret_1d):.1f}% today.")
    else:
        parts.append(f"{ticker} barely moved today.")

    if "Beaten down" in catalyst or "dropped hard" in catalyst:
        parts.append(
            f"The stock has been beaten down {abs(ret_5d):.0f}% this week — "
            f"like a clearance sale price. Stocks that drop this hard usually "
            f"bounce back within a few days."
        )
    elif "Climbing fast" in catalyst:
        parts.append(
            f"It's been climbing {ret_5d:+.1f}% this week and big buyers are piling in. "
            f"When a stock gets this kind of attention, the run usually keeps going."
        )
    elif "Big jump today" in catalyst:
        parts.append(
            f"The stock surged {ret_1d:+.1f}% today on {vol_ratio:.0f}x normal trading volume. "
            f"That kind of big-money move often continues for a few more days."
        )
    elif "Unusual" in catalyst:
        parts.append(
            f"Way more people are buying and selling this stock than normal — "
            f"{vol_ratio:.0f}x the usual activity. That usually means something big is happening."
        )
    else:
        parts.append(
            f"This stock moves a lot day-to-day (about {atr_pct:.0f}% per day), "
            f"which means there's a real chance for a big swing."
        )

    if "Insider buying" in catalyst:
        parts.append(
            "The company's own executives are buying shares with their own money — "
            "they know the business better than anyone, and they think it's cheap right now."
        )

    if sentiment_score is not None and sentiment_label:
        if sentiment_label == "bullish" and direction == "long":
            parts.append("Every recent article about this stock has been positive — the news is on your side here.")
        elif sentiment_label == "bearish" and direction == "long":
            parts.append(
                "The news has been negative lately, but that's actually "
                "part of why the price is low — a contrarian opportunity."
            )
        elif sentiment_label == "bullish" and direction == "short":
            parts.append(
                "The news has been positive, which makes this a riskier bet against the stock — keep a tight stop."
            )
        elif sentiment_label == "bearish" and direction == "short":
            parts.append(
                "The news about this company has been mostly bad — which supports the idea of betting against it."
            )

    gain_pct = abs(target - price) / price * 100
    loss_pct = abs(stop - price) / price * 100
    parts.append(
        f"If it works out, you could make about {gain_pct:.0f}% in {hold_label}. "
        f"If it goes the wrong way, cut your losses at -{loss_pct:.0f}% — don't hold and hope."
    )

    if atr_pct > 6:
        parts.append(
            "Fair warning: this stock can swing 5-10% in a single day. Only put in money you're genuinely okay losing."
        )
    else:
        parts.append("This is a risky bet — don't put in more than a small amount you can afford to lose.")

    return " ".join(parts)


def _log_swing_picks_to_shadow_book(picks: list[dict]) -> None:
    """Auto-log swing picks to the signal audit trail as phantom trades."""
    from backend.models.schemas import PhantomTrade, StrategyName, TradeSignal
    from backend.tracker.trade_journal import TradeJournal

    journal = TradeJournal()
    for pick in picks:
        try:
            sig = TradeSignal(
                strategy=StrategyName.INTRADAY,
                ticker=pick["ticker"],
                direction=pick.get("direction", "long"),
                conviction=pick.get("score", 50) / 100,
                kelly_size_pct=1.0,
                entry_price=pick["entry"],
                stop_loss=pick["stop"],
                target=pick["target"],
                max_hold_days=10,
                edge_reason=pick.get("catalyst", "swing pick"),
                kill_condition=f"Stop at {pick['stop']} or time stop",
                expected_sharpe=1.0,
                signal_score=pick.get("score", 50),
            )
            _auditor.log_signal(sig, acted_on=False)
            phantom = PhantomTrade(
                ticker=pick["ticker"],
                direction=pick.get("direction", "long"),
                strategy=StrategyName.INTRADAY,
                signal_score=pick.get("score", 50),
                signal_date=date.today(),
                entry_price_suggested=pick["entry"],
                stop_suggested=pick["stop"],
                target_suggested=pick["target"],
                pass_reason="auto-logged (swing pick)",
            )
            journal.log_phantom(phantom)
        except Exception:
            logger.debug("Failed to shadow-log swing pick for %s", pick.get("ticker"))


def _get_current_regime() -> str:
    """Get regime from pipeline cache or compute it."""
    cached = data_cache.get("pipeline:regime")
    if cached and isinstance(cached, dict) and "regime" in cached:
        return cached["regime"]
    try:
        from backend.regime.detector import detect_regime

        spy_df = _fetcher.get_daily_ohlcv("SPY", period="3mo", live=False)
        vix_df = _fetcher.get_daily_ohlcv("^VIX", period="3mo", live=False)
        result = detect_regime(vix_df, spy_df)
        return result.get("regime", "unknown")
    except Exception:
        return "unknown"


def _apply_sector_cap(picks: list[dict], max_per_sector: int = 2) -> list[dict]:
    """Enforce sector diversification: max N picks per sector."""
    sector_count: dict[str, int] = {}
    result: list[dict] = []
    for p in picks:
        sector = p.get("sector", "Unknown")
        cnt = sector_count.get(sector, 0)
        if cnt < max_per_sector:
            result.append(p)
            sector_count[sector] = cnt + 1
    return result


def _run_swing_scan(min_return_pct: float, max_hold_days: int) -> dict:
    """Scan the full universe for swing picks (runs in thread pool)."""
    universe = _get_scan_universe()
    regime = _get_current_regime()
    logger.info(
        "Swing scan: scanning %d tickers for %.0f%%+ in %dd (regime=%s)...",
        len(universe),
        min_return_pct,
        max_hold_days,
        regime,
    )

    import yfinance as yf

    batch_ohlcv: dict[str, pd.DataFrame] = {}
    try:
        raw = yf.download(universe, period="3mo", group_by="ticker", threads=False, progress=False)
        if not raw.empty:
            for ticker in universe:
                try:
                    df = raw[ticker].dropna(how="all") if len(universe) > 1 else raw
                    if not df.empty:
                        batch_ohlcv[ticker] = df
                except (KeyError, Exception):
                    pass
    except Exception:
        logger.warning("Batch OHLCV download failed in sync scan")

    quick_trades: list[dict] = []
    swing_trades: list[dict] = []
    scanned = 0

    for ticker in universe:
        ohlcv = batch_ohlcv.get(ticker)
        result = _analyze_ticker_for_swing(
            ticker, max_hold_days, min_return_pct, regime=regime, pre_fetched_ohlcv=ohlcv
        )
        scanned += 1
        if result is None:
            continue

        if result["hold_bucket"] == "quick":
            quick_trades.append(result)
        else:
            swing_trades.append(result)

    all_candidates = quick_trades + swing_trades
    all_candidates.sort(key=lambda x: x["score"], reverse=True)

    ranked = _ai_rerank(all_candidates)
    if ranked is not None:
        all_candidates = ranked
        logger.info("AI re-ranked %d swing candidates", len(all_candidates))

    all_candidates = _apply_sector_cap(all_candidates)

    quick_trades = [p for p in all_candidates if p["hold_bucket"] == "quick"][:15]
    swing_trades = [p for p in all_candidates if p["hold_bucket"] == "swing"][:15]

    logger.info(
        "Swing scan complete: %d quick + %d swing picks from %d tickers",
        len(quick_trades),
        len(swing_trades),
        scanned,
    )

    return {
        "quick_trades": quick_trades,
        "swing_trades": swing_trades,
        "scan_stats": {
            "tickers_scanned": scanned,
            "timestamp": datetime.now(UTC).isoformat(),
            "min_return_target": min_return_pct,
            "max_hold_days": max_hold_days,
        },
    }


# Background scan state (in-memory, single-worker safe)
_scan_state: dict = {
    "status": "idle",  # idle | scanning | done | error
    "progress": 0,  # tickers scanned so far
    "total": 0,  # total tickers to scan
    "step": "",  # current phase description
    "result": None,  # scan results when done
    "result_timestamp": None,
    "started_at": None,
    "ai_summary": None,  # AI analysis of picks
    "error": None,
}


def _ai_rerank(candidates: list[dict]) -> list[dict] | None:
    """Send candidates to Claude for AI ranking. Returns re-ordered list or None on failure."""
    if not candidates:
        return None
    try:
        from backend.ai.market_ai import ai_rank_swing_picks
        from backend.regime.detector import detect_regime

        spy_df = _fetcher.get_daily_ohlcv("SPY", period="3mo", live=False)
        vix_df = _fetcher.get_daily_ohlcv("^VIX", period="3mo", live=False)
        regime_result = detect_regime(vix_df, spy_df)
        regime = regime_result.get("regime", "unknown")

        ai_result = ai_rank_swing_picks(regime, candidates[:30])
        if not ai_result or "ranked" not in ai_result:
            logger.info("AI ranking returned no results, using hardcoded scores")
            return None

        ranked_list = ai_result["ranked"]
        ticker_map = {c["ticker"]: c for c in candidates}
        reordered: list[dict] = []

        for item in ranked_list:
            ticker = item.get("ticker", "")
            if ticker not in ticker_map:
                continue
            pick = ticker_map.pop(ticker)
            pick["score"] = item.get("score", pick["score"])
            if item.get("analysis"):
                pick["analysis"] = item["analysis"]
            reordered.append(pick)

        for leftover in ticker_map.values():
            reordered.append(leftover)

        return reordered
    except Exception as e:
        logger.warning("AI ranking failed, falling back to hardcoded scores: %s", e)
        return None


_SCAN_WORKERS = 6


def _run_scan_background(min_return_pct: float, max_hold_days: int) -> None:
    """Run scan and store results in _scan_state (called from thread pool).

    Uses a parallel thread pool to analyze tickers concurrently since each
    ticker analysis is I/O-bound (yfinance HTTP calls).
    AI analysis is generated server-side so results arrive complete.
    """
    from backend.progress import ScanProgressTracker

    global _scan_state
    try:
        _scan_state["status"] = "scanning"
        _scan_state["started_at"] = datetime.now(UTC).isoformat()
        _scan_state["error"] = None

        tracker = ScanProgressTracker.create(
            [
                ("universe", 5),
                ("scan", 180),
                ("ai_rank", 15),
                ("filter", 2),
                ("ai_summary", 15),
            ],
            _scan_state,
            "progress:swing",
        )

        tracker.start_phase("universe", "Building scan universe...")

        universe = _get_scan_universe()
        regime = _get_current_regime()
        _scan_state["total"] = len(universe)
        logger.info(
            "Background swing scan: %d tickers, %.0f%%+ in %dd (workers=%d, regime=%s)",
            len(universe),
            min_return_pct,
            max_hold_days,
            _SCAN_WORKERS,
            regime,
        )

        quick_trades: list[dict] = []
        swing_trades: list[dict] = []
        progress = 0
        total = len(universe)

        tracker.start_phase("scan", "Batch-fetching OHLCV data...")

        import yfinance as yf

        batch_ohlcv: dict[str, pd.DataFrame] = {}
        try:
            raw = yf.download(
                universe,
                period="3mo",
                group_by="ticker",
                threads=False,
                progress=False,
            )
            if not raw.empty:
                for ticker in universe:
                    try:
                        df = raw[ticker].dropna(how="all") if len(universe) > 1 else raw
                        if not df.empty:
                            batch_ohlcv[ticker] = df
                    except (KeyError, Exception):
                        pass
            logger.info("Batch OHLCV: got %d/%d tickers", len(batch_ohlcv), len(universe))
        except Exception:
            logger.warning("Batch OHLCV download failed, will fetch individually")

        tracker.update_within_phase(0, total, f"Checking stocks... 0/{total}")

        def _analyze_one(ticker: str) -> dict | None:
            ohlcv = batch_ohlcv.get(ticker)
            return _analyze_ticker_for_swing(
                ticker,
                max_hold_days,
                min_return_pct,
                regime=regime,
                pre_fetched_ohlcv=ohlcv,
            )

        scan_timeout_sec = 600

        with ThreadPoolExecutor(max_workers=_SCAN_WORKERS) as pool:
            futures = {pool.submit(_analyze_one, t): t for t in universe}
            try:
                for future in as_completed(futures, timeout=scan_timeout_sec):
                    progress += 1
                    tracker.update_within_phase(
                        progress,
                        total,
                        f"Checking stocks... {progress}/{total}",
                    )
                    try:
                        result = future.result(timeout=30)
                    except (TimeoutError, Exception):
                        continue
                    if result is not None:
                        if result["hold_bucket"] == "quick":
                            quick_trades.append(result)
                        else:
                            swing_trades.append(result)
            except TimeoutError:
                logger.warning(
                    "Swing scan timeout after %ds, returning %d partial results",
                    scan_timeout_sec,
                    len(quick_trades) + len(swing_trades),
                )
                pool.shutdown(wait=False, cancel_futures=True)

        all_candidates = quick_trades + swing_trades
        all_candidates.sort(key=lambda x: x["score"], reverse=True)

        tracker.start_phase("ai_rank", "AI ranking candidates...")
        ranked = _ai_rerank(all_candidates)
        if ranked is not None:
            all_candidates = ranked
            logger.info("AI re-ranked %d swing candidates", len(all_candidates))

        tracker.start_phase("filter", "Filtering and logging...")
        all_candidates = _apply_sector_cap(all_candidates)

        quick_trades = [p for p in all_candidates if p["hold_bucket"] == "quick"][:15]
        swing_trades = [p for p in all_candidates if p["hold_bucket"] == "swing"][:15]

        all_picks = sorted(
            quick_trades + swing_trades, key=lambda x: x["score"], reverse=True
        )
        _log_swing_picks_to_shadow_book(all_picks)

        result_data = {
            "quick_trades": quick_trades,
            "swing_trades": swing_trades,
            "scan_stats": {
                "tickers_scanned": len(universe),
                "timestamp": datetime.now(UTC).isoformat(),
                "min_return_target": min_return_pct,
                "max_hold_days": max_hold_days,
            },
        }

        tracker.start_phase("ai_summary", "AI analyzing setups...")
        ai_summary = None
        try:
            from backend.data.ticker_intelligence import format_sentiment_block, get_universe_sentiment

            univ_sentiment = get_universe_sentiment()
            sentiment_block = format_sentiment_block(univ_sentiment)
        except Exception:
            sentiment_block = ""
            logger.debug("Universe sentiment unavailable for swing AI summary")
        try:
            ai_summary = ai_swing_summary(regime, all_picks, sentiment_block=sentiment_block)
        except Exception as e:
            logger.warning("AI swing analysis failed (scan continues): %s", e)

        tracker.finish()
        tracker.save_history("progress:swing")
        _scan_state["result"] = result_data
        _scan_state["result_timestamp"] = datetime.now(UTC).isoformat()
        _scan_state["ai_summary"] = ai_summary
        _scan_state["status"] = "done"
        data_cache.set("swing:last_result", result_data, ttl_hours=24.0)
        data_cache.set("swing:ai_summary", ai_summary, ttl_hours=24.0)
        logger.info("Background swing scan done: %d quick + %d swing", len(quick_trades), len(swing_trades))
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
    with _scan_lock:
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
        _scan_state["ai_summary"] = None

    _executor.submit(_run_scan_background, min_return_pct, max_hold_days)
    return {"status": "started"}


@router.get("/status")
async def get_scan_status() -> dict:
    """Poll scan progress. Returns status, progress, and results when done."""
    status = _scan_state["status"]
    result = _scan_state["result"] if status == "done" else None
    ai_summary = _scan_state.get("ai_summary")
    result_timestamp = _scan_state.get("result_timestamp")
    cached_at: str | None = None

    if result is None and status == "idle":
        cached = data_cache.get("swing:last_result")
        if cached:
            result = cached
            ai_summary = data_cache.get("swing:ai_summary")
            if isinstance(cached, dict) and isinstance(cached.get("scan_stats"), dict):
                cached_at = cached["scan_stats"].get("timestamp")
            result_timestamp = result_timestamp or cached_at

    return {
        "status": status,
        "progress": _scan_state["progress"],
        "total": _scan_state["total"],
        "step": _scan_state.get("step", ""),
        "result": result,
        "result_timestamp": result_timestamp,
        "cached_at": cached_at,
        "ai_summary": ai_summary,
        "error": _scan_state["error"],
    }


@router.get("/stream")
async def stream_swing_scan():
    """SSE endpoint — streams swing scan progress in real-time, then the
    full result (including AI analysis) as a single terminal event."""

    async def _event_stream():
        prev_snapshot = ""
        while True:
            snap = {
                "status": _scan_state["status"],
                "progress": _scan_state["progress"],
                "total": _scan_state["total"],
                "step": _scan_state.get("step", ""),
                "error": _scan_state["error"],
            }
            encoded = json.dumps(snap, default=str)

            if _scan_state["status"] == "done":
                snap["result"] = _scan_state["result"]
                snap["result_timestamp"] = _scan_state.get("result_timestamp")
                snap["ai_summary"] = _scan_state.get("ai_summary")
                yield f"data: {json.dumps(snap, default=str)}\n\n"
                return

            if _scan_state["status"] == "error":
                yield f"data: {encoded}\n\n"
                return

            if _scan_state["status"] == "idle":
                cached = data_cache.get("swing:last_result")
                if cached:
                    snap["status"] = "done"
                    snap["result"] = cached
                    snap["result_timestamp"] = _scan_state.get("result_timestamp")
                    snap["ai_summary"] = data_cache.get("swing:ai_summary")
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


@router.get("/picks")
async def get_swing_picks(
    min_return_pct: float = Query(default=30.0, ge=5.0, le=100.0, description="Minimum target return %"),
    max_hold_days: int = Query(default=10, ge=1, le=30, description="Maximum hold period in days"),
    refresh: bool = Query(False, description="Force live scan, bypass pipeline cache"),
) -> dict:
    """Swing picks from pipeline cache (instant) or live scan."""
    if not refresh:
        cached = data_cache.get("pipeline:swing")
        if cached and isinstance(cached, dict):
            return cached

    from backend.pipeline import refresh_swing

    result = refresh_swing()
    if result:
        return result

    loop = asyncio.get_event_loop()
    live_result = await loop.run_in_executor(_executor, _run_swing_scan, min_return_pct, max_hold_days)
    return {"data": live_result, "refreshed_at": datetime.now(UTC).isoformat()}

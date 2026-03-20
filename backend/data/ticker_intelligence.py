"""Unified ticker intelligence layer — single source of truth for all features.

Assembles fundamentals, sentiment, DCF, technicals, insider, and earnings
data into a standard TickerIntel dataclass. Every AI prompt that needs ticker
context uses format_intel_block() for consistent data presentation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class TickerIntel:
    ticker: str
    name: str
    sector: str
    industry: str
    price: float

    market_cap: float | None = None
    pe_ratio: float | None = None
    forward_pe: float | None = None
    peg_ratio: float | None = None
    revenue_growth: float | None = None
    profit_margin: float | None = None
    fcf_yield: float | None = None
    debt_to_equity: float | None = None
    analyst_target: float | None = None
    analyst_count_buy: int | None = None
    analyst_count_hold: int | None = None
    analyst_count_sell: int | None = None

    sentiment_score: float | None = None
    sentiment_label: str | None = None
    sentiment_articles: int | None = None
    sentiment_model: str | None = None

    dcf_fair_value: float | None = None
    dcf_upside_pct: float | None = None
    dcf_verdict: str | None = None

    rsi: float | None = None
    sma_20: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    above_sma_50: bool | None = None
    above_sma_200: bool | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    ret_20d: float | None = None
    ret_60d: float | None = None
    volume_ratio: float | None = None

    insider_score: float | None = None
    insider_cluster: bool | None = None
    insider_csuite: bool | None = None

    earnings_next_date: str | None = None
    earnings_last_surprise: float | None = None
    earnings_beat_rate: float | None = None


@dataclass
class UniverseSentiment:
    pct_bullish: float
    pct_bearish: float
    pct_neutral: float
    top_bullish: list[tuple[str, float]] = field(default_factory=list)
    top_bearish: list[tuple[str, float]] = field(default_factory=list)
    total_tickers: int = 0
    avg_score: float = 50.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_technicals_lite(ohlcv: pd.DataFrame) -> dict:
    """Subset of technicals needed for TickerIntel (no ATR/trend/support)."""
    if ohlcv.empty or len(ohlcv) < 20:
        return {}

    close = ohlcv["Close"]
    volume = ohlcv["Volume"]
    current = float(close.iloc[-1])

    sma_20 = float(close.tail(20).mean())
    sma_50 = float(close.tail(50).mean()) if len(close) >= 50 else None
    sma_200 = float(close.tail(200).mean()) if len(close) >= 200 else None

    delta = close.diff()
    gain = delta.where(delta > 0, 0).tail(14).mean()
    loss = (-delta.where(delta < 0, 0)).tail(14).mean()
    rs = gain / loss if loss > 0 else 100
    rsi = float(100 - (100 / (1 + rs)))

    yearly = close.tail(252)
    high_52w = float(yearly.max())
    low_52w = float(yearly.min())

    ret_20d = float((close.iloc[-1] / close.iloc[-20] - 1) * 100) if len(close) >= 20 else None
    ret_60d = float((close.iloc[-1] / close.iloc[-60] - 1) * 100) if len(close) >= 60 else None

    avg_vol_20d = float(volume.tail(20).mean())
    latest_vol = float(volume.iloc[-1])
    vol_ratio = round(latest_vol / avg_vol_20d, 2) if avg_vol_20d > 0 else 1.0

    return {
        "rsi": round(rsi, 1),
        "sma_20": round(sma_20, 2),
        "sma_50": round(sma_50, 2) if sma_50 else None,
        "sma_200": round(sma_200, 2) if sma_200 else None,
        "above_sma_50": current > sma_50 if sma_50 else None,
        "above_sma_200": current > sma_200 if sma_200 else None,
        "high_52w": round(high_52w, 2),
        "low_52w": round(low_52w, 2),
        "ret_20d": round(ret_20d, 1) if ret_20d is not None else None,
        "ret_60d": round(ret_60d, 1) if ret_60d is not None else None,
        "volume_ratio": vol_ratio,
    }


def _extract_analyst_counts(fetcher_instance, ticker: str) -> dict:
    """Latest buy/hold/sell analyst recommendation counts."""
    try:
        trends = fetcher_instance.get_recommendation_trends(ticker)
        if not trends:
            return {}
        latest = trends[0]
        buy = int(latest.get("strong_buy", 0) or 0) + int(latest.get("buy", 0) or 0)
        hold = int(latest.get("hold", 0) or 0)
        sell = int(latest.get("sell", 0) or 0) + int(latest.get("strong_sell", 0) or 0)
        return {"buy": buy, "hold": hold, "sell": sell}
    except Exception:
        logger.debug("Analyst counts unavailable for %s", ticker)
        return {}


def _extract_earnings_stats(earnings: list[dict]) -> dict:
    """Next earnings date, last surprise %, and historical beat rate."""
    if not earnings:
        return {}

    result: dict = {}
    today_str = date.today().isoformat()

    for e in earnings:
        d = e.get("report_date") or e.get("date")
        if d is not None and str(d) >= today_str:
            result["next_date"] = str(d)
            break

    for e in earnings:
        surprise = e.get("surprise_pct")
        if surprise is not None:
            result["last_surprise"] = float(surprise)
            break

    beats, total = 0, 0
    for e in earnings:
        actual = e.get("eps_actual")
        estimate = e.get("eps_estimate")
        if actual is not None and estimate is not None:
            total += 1
            if actual > estimate:
                beats += 1
    if total > 0:
        result["beat_rate"] = round(beats / total * 100, 0)

    return result


def _lookup_ticker_name(ticker: str) -> tuple[str, str, str]:
    """(name, sector, sub_industry) from S&P 500 universe cache."""
    try:
        from backend.data.universe import fetch_sp500_constituents

        df = fetch_sp500_constituents()
        if not df.empty:
            match = df.loc[df["ticker"] == ticker.upper()]
            if not match.empty:
                row = match.iloc[0]
                return (
                    str(row.get("name", ticker)),
                    str(row.get("sector", "Unknown")),
                    str(row.get("sub_industry", "Unknown")),
                )
    except Exception:
        pass
    return ticker, "Unknown", "Unknown"


def _try_dcf_cache(ticker: str) -> dict | None:
    """Check for a cached DCF result without triggering a live computation."""
    try:
        from backend.data.cache import data_cache

        result = data_cache.get(f"dcf:{ticker.upper()}")
        return result if isinstance(result, dict) else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_ticker_intel(
    ticker: str,
    include_dcf: bool = False,
) -> TickerIntel:
    """Assemble all available data for a ticker into a TickerIntel.

    Reads caches first (instant) and falls back to live yfinance.
    When *include_dcf* is False, the DCF fields are still populated from
    cache if a recent result exists (no extra API calls).
    """
    from backend.data import fetcher
    from backend.data.sentiment_cache import sentiment_cache

    ticker = ticker.upper()

    name, sector, industry = _lookup_ticker_name(ticker)

    fundamentals: dict = {}
    try:
        fundamentals = fetcher.get_fundamentals(ticker) or {}
    except Exception:
        logger.warning("Fundamentals fetch failed for %s", ticker)

    if sector == "Unknown" and fundamentals.get("sector"):
        sector = fundamentals["sector"]
    if industry == "Unknown" and fundamentals.get("industry"):
        industry = fundamentals["industry"]

    price = 0.0
    try:
        price = fetcher.get_current_price(ticker) or 0.0
    except Exception:
        logger.warning("Price fetch failed for %s", ticker)

    # --- Sentiment (in-memory cache, instant) ---
    sent = sentiment_cache.get(ticker)

    # --- Technicals from OHLCV ---
    tech: dict = {}
    try:
        ohlcv = fetcher.get_daily_ohlcv(ticker, period="2y")
        if not ohlcv.empty:
            tech = _compute_technicals_lite(ohlcv)
            if price <= 0:
                price = float(ohlcv["Close"].iloc[-1])
    except Exception:
        logger.warning("OHLCV/technicals fetch failed for %s", ticker)

    # --- DCF: always try cache, compute live only when requested ---
    dcf = _try_dcf_cache(ticker)
    if dcf is None and include_dcf:
        try:
            from backend.signals.dcf import compute_dcf

            dcf = compute_dcf(
                ticker,
                fetcher,
                sentiment_score=sent.composite_score if sent else None,
            )
        except Exception:
            logger.warning("DCF computation failed for %s", ticker)

    # --- FCF Yield (only when we have market cap and include_dcf) ---
    fcf_yield: float | None = None
    mc = fundamentals.get("market_cap")
    if include_dcf and mc and mc > 0:
        try:
            cf = fetcher.get_cashflow(ticker)
            if cf is not None and not (isinstance(cf, pd.DataFrame) and cf.empty):
                from backend.signals.dcf import _extract_fcf

                fcf_history = _extract_fcf(cf)
                if fcf_history and fcf_history[0] > 0:
                    fcf_yield = round(fcf_history[0] / mc * 100, 2)
        except Exception:
            pass

    # --- Insider ---
    insider: dict = {}
    try:
        insider = fetcher.get_insider_buying_score(ticker)
    except Exception:
        logger.debug("Insider score unavailable for %s", ticker)

    # --- Earnings ---
    earnings_stats: dict = {}
    try:
        earnings = fetcher.get_earnings_data(ticker)
        earnings_stats = _extract_earnings_stats(earnings)
    except Exception:
        logger.debug("Earnings data unavailable for %s", ticker)

    # --- Analyst counts ---
    analyst = _extract_analyst_counts(fetcher, ticker)

    return TickerIntel(
        ticker=ticker,
        name=name,
        sector=sector,
        industry=industry,
        price=round(price, 2),
        market_cap=fundamentals.get("market_cap"),
        pe_ratio=fundamentals.get("pe_ratio"),
        forward_pe=fundamentals.get("forward_pe"),
        peg_ratio=fundamentals.get("peg_ratio"),
        revenue_growth=fundamentals.get("revenue_growth"),
        profit_margin=fundamentals.get("profit_margin"),
        fcf_yield=fcf_yield,
        debt_to_equity=fundamentals.get("debt_to_equity"),
        analyst_target=fundamentals.get("analyst_target"),
        analyst_count_buy=analyst.get("buy"),
        analyst_count_hold=analyst.get("hold"),
        analyst_count_sell=analyst.get("sell"),
        sentiment_score=sent.composite_score if sent else None,
        sentiment_label=sent.sentiment_label if sent else None,
        sentiment_articles=sent.article_count if sent else None,
        sentiment_model=sent.model_used if sent else None,
        dcf_fair_value=dcf["intrinsic_value"] if dcf else None,
        dcf_upside_pct=dcf["upside_pct"] if dcf else None,
        dcf_verdict=dcf["verdict"] if dcf else None,
        rsi=tech.get("rsi"),
        sma_20=tech.get("sma_20"),
        sma_50=tech.get("sma_50"),
        sma_200=tech.get("sma_200"),
        above_sma_50=tech.get("above_sma_50"),
        above_sma_200=tech.get("above_sma_200"),
        high_52w=tech.get("high_52w"),
        low_52w=tech.get("low_52w"),
        ret_20d=tech.get("ret_20d"),
        ret_60d=tech.get("ret_60d"),
        volume_ratio=tech.get("volume_ratio"),
        insider_score=insider.get("signal_score"),
        insider_cluster=insider.get("cluster_buy"),
        insider_csuite=insider.get("c_suite_buying"),
        earnings_next_date=earnings_stats.get("next_date"),
        earnings_last_surprise=earnings_stats.get("last_surprise"),
        earnings_beat_rate=earnings_stats.get("beat_rate"),
    )


def get_universe_sentiment() -> UniverseSentiment:
    """Aggregate FinBERT sentiment stats across all cached tickers."""
    from backend.data.sentiment_cache import sentiment_cache

    tickers = sentiment_cache.all_tickers()
    if not tickers:
        return UniverseSentiment(
            pct_bullish=0,
            pct_bearish=0,
            pct_neutral=100,
            total_tickers=0,
            avg_score=50.0,
        )

    scores: list[tuple[str, float, str]] = []
    for t in tickers:
        entry = sentiment_cache.get(t)
        if entry:
            scores.append((t, entry.composite_score, entry.sentiment_label))

    if not scores:
        return UniverseSentiment(
            pct_bullish=0,
            pct_bearish=0,
            pct_neutral=100,
            total_tickers=0,
            avg_score=50.0,
        )

    total = len(scores)
    bullish = sum(1 for _, _, label in scores if label == "bullish")
    bearish = sum(1 for _, _, label in scores if label == "bearish")
    neutral = total - bullish - bearish

    avg_score = sum(s for _, s, _ in scores) / total

    sorted_by_score = sorted(scores, key=lambda x: x[1], reverse=True)
    top_bullish = [(t, s) for t, s, _ in sorted_by_score[:5]]
    top_bearish = [(t, s) for t, s, _ in sorted_by_score[-5:]]
    top_bearish.reverse()

    return UniverseSentiment(
        pct_bullish=round(bullish / total * 100, 1),
        pct_bearish=round(bearish / total * 100, 1),
        pct_neutral=round(neutral / total * 100, 1),
        top_bullish=top_bullish,
        top_bearish=top_bearish,
        total_tickers=total,
        avg_score=round(avg_score, 1),
    )


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _fmt_cap(val: float | None) -> str:
    if val is None:
        return "N/A"
    if val >= 1e12:
        return f"${val / 1e12:.1f}T"
    if val >= 1e9:
        return f"${val / 1e9:.1f}B"
    if val >= 1e6:
        return f"${val / 1e6:.0f}M"
    return f"${val:,.0f}"


def _fmt_pct(val: float | None, decimals: int = 1) -> str:
    if val is None:
        return "N/A"
    return f"{val:.{decimals}f}%"


def _fmt_num(val: float | int | None, decimals: int = 1) -> str:
    if val is None:
        return "N/A"
    return f"{val:.{decimals}f}"


def _check(val: bool | None) -> str:
    if val is None:
        return "?"
    return "✓" if val else "✗"


def format_intel_block(intel: TickerIntel) -> str:
    """Standard text block injected into any Claude prompt needing ticker context.

    Example output::

        [AAPL — Apple Inc. | Technology | $195.20]
        Fundamentals: Market cap $3.0T, P/E 28.5, Fwd P/E 26.1, Rev growth 8%, Margin 26%
        Valuation: DCF fair value $210 (+7.6% upside), analyst target $215, PEG 2.1
        Sentiment: FinBERT 82/100 BULLISH (14 articles), model=finbert
        Technicals: RSI 55, above SMA50 ✓, above SMA200 ✓, 52w: $164-$199, +12.3% (60d)
        Insider: Score 45, no cluster buying
        Earnings: Next Apr 24, last surprise +4.2%, beat rate 88%
    """
    rev_display = _fmt_pct(intel.revenue_growth * 100 if intel.revenue_growth is not None else None, 0)
    margin_display = _fmt_pct(intel.profit_margin * 100 if intel.profit_margin is not None else None, 0)

    lines: list[str] = [
        f"[{intel.ticker} — {intel.name} | {intel.sector} | ${intel.price:.2f}]",
        (
            f"Fundamentals: Market cap {_fmt_cap(intel.market_cap)}, "
            f"P/E {_fmt_num(intel.pe_ratio)}, Fwd P/E {_fmt_num(intel.forward_pe)}, "
            f"Rev growth {rev_display}, Margin {margin_display}"
        ),
    ]

    # Valuation
    val_parts: list[str] = []
    if intel.dcf_fair_value is not None:
        val_parts.append(f"DCF fair value ${intel.dcf_fair_value:.0f} ({intel.dcf_upside_pct:+.1f}% upside)")
    if intel.analyst_target is not None:
        val_parts.append(f"analyst target ${intel.analyst_target:.0f}")
    if intel.peg_ratio is not None:
        val_parts.append(f"PEG {intel.peg_ratio:.1f}")
    if intel.fcf_yield is not None:
        val_parts.append(f"FCF yield {intel.fcf_yield:.1f}%")
    if val_parts:
        lines.append(f"Valuation: {', '.join(val_parts)}")

    # Analyst consensus
    if intel.analyst_count_buy is not None:
        total_a = (intel.analyst_count_buy or 0) + (intel.analyst_count_hold or 0) + (intel.analyst_count_sell or 0)
        if total_a > 0:
            lines.append(
                f"Analysts: {intel.analyst_count_buy} buy, "
                f"{intel.analyst_count_hold} hold, "
                f"{intel.analyst_count_sell} sell"
            )

    # Sentiment
    if intel.sentiment_score is not None:
        lines.append(
            f"Sentiment: FinBERT {intel.sentiment_score:.0f}/100 "
            f"{(intel.sentiment_label or 'N/A').upper()} "
            f"({intel.sentiment_articles or 0} articles), "
            f"model={intel.sentiment_model or 'N/A'}"
        )

    # Technicals
    tech_parts: list[str] = []
    if intel.rsi is not None:
        tech_parts.append(f"RSI {intel.rsi:.0f}")
    if intel.above_sma_50 is not None:
        tech_parts.append(f"above SMA50 {_check(intel.above_sma_50)}")
    if intel.above_sma_200 is not None:
        tech_parts.append(f"above SMA200 {_check(intel.above_sma_200)}")
    if intel.high_52w is not None and intel.low_52w is not None:
        tech_parts.append(f"52w: ${intel.low_52w:.0f}-${intel.high_52w:.0f}")
    if intel.ret_60d is not None:
        tech_parts.append(f"{intel.ret_60d:+.1f}% (60d)")
    if intel.volume_ratio is not None:
        tech_parts.append(f"vol ratio {intel.volume_ratio:.1f}x")
    if tech_parts:
        lines.append(f"Technicals: {', '.join(tech_parts)}")

    # Insider
    insider_parts: list[str] = []
    if intel.insider_score is not None:
        insider_parts.append(f"Score {intel.insider_score:.0f}")
    if intel.insider_cluster:
        insider_parts.append("cluster buying detected")
    elif intel.insider_score is not None:
        insider_parts.append("no cluster buying")
    if intel.insider_csuite:
        insider_parts.append("C-suite buying")
    if insider_parts:
        lines.append(f"Insider: {', '.join(insider_parts)}")

    # Earnings
    earn_parts: list[str] = []
    if intel.earnings_next_date:
        earn_parts.append(f"Next {intel.earnings_next_date}")
    if intel.earnings_last_surprise is not None:
        earn_parts.append(f"last surprise {intel.earnings_last_surprise:+.1f}%")
    if intel.earnings_beat_rate is not None:
        earn_parts.append(f"beat rate {intel.earnings_beat_rate:.0f}%")
    if earn_parts:
        lines.append(f"Earnings: {', '.join(earn_parts)}")

    return "\n".join(lines)


def format_sentiment_block(univ: UniverseSentiment) -> str:
    """Universe-level sentiment context block for Claude prompts.

    Example output::

        [SENTIMENT CONTEXT — AI-Analyzed News Sentiment]
        Universe: 487 stocks analyzed, avg score 58/100
        Distribution: 42% bullish, 38% neutral, 20% bearish
        Most bullish: NVDA (92), SMCI (88), META (85), PLTR (83), AVGO (81)
        Most bearish: PFE (22), BA (25), NKE (28), DIS (31), INTC (33)
    """
    lines: list[str] = [
        "[SENTIMENT CONTEXT — AI-Analyzed News Sentiment]",
        (f"Universe: {univ.total_tickers} stocks analyzed, avg score {univ.avg_score:.0f}/100"),
        (
            f"Distribution: {univ.pct_bullish:.0f}% bullish, "
            f"{univ.pct_neutral:.0f}% neutral, "
            f"{univ.pct_bearish:.0f}% bearish"
        ),
    ]

    if univ.top_bullish:
        bulls = ", ".join(f"{t} ({s:.0f})" for t, s in univ.top_bullish[:5])
        lines.append(f"Most bullish: {bulls}")

    if univ.top_bearish:
        bears = ", ".join(f"{t} ({s:.0f})" for t, s in univ.top_bearish[:5])
        lines.append(f"Most bearish: {bears}")

    return "\n".join(lines)

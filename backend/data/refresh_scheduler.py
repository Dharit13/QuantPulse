"""Background data refresh scheduler — pre-fetches market data into Supabase.

Each job fetches from external APIs and upserts into structured tables.
The DataFetcher then reads from these tables instead of calling APIs,
eliminating on-demand latency for strategies and scanning.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, date, datetime, timedelta

import pandas as pd

from backend.config import settings
from backend.data.sources.yfinance_src import yfinance_source
from backend.models.database import get_supabase, reset_client

logger = logging.getLogger(__name__)

BATCH_SIZE = 50
_MAX_RETRIES = 2
_RETRY_DELAY = 1.0


def _upsert_with_retry(table: str, rows: list[dict], on_conflict: str) -> None:
    """Upsert rows in small batches with retry on transient Supabase errors."""
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        for attempt in range(_MAX_RETRIES + 1):
            try:
                get_supabase().table(table).upsert(batch, on_conflict=on_conflict).execute()
                break
            except Exception as e:
                err_msg = str(e).lower()
                retriable = any(
                    k in err_msg for k in ["timeout", "57014", "disconnected", "connection", "reset", "broken pipe"]
                )
                if retriable and attempt < _MAX_RETRIES:
                    reset_client()
                    time.sleep(_RETRY_DELAY * (attempt + 1))
                    logger.debug("Supabase upsert retry %d for %s: %s", attempt + 1, table, e)
                    continue
                raise


def _get_universe_tickers() -> list[str]:
    """Get tickers from the universe table, falling back to Wikipedia fetch."""
    try:
        sb = get_supabase()
        result = sb.table("universe").select("ticker").execute()
        if result.data:
            return [r["ticker"] for r in result.data]
    except Exception:
        logger.warning("Failed to read universe table")

    from backend.data.universe import fetch_sp500_constituents

    df = fetch_sp500_constituents()
    return df["ticker"].tolist() if not df.empty else []


# ── Universe ────────────────────────────────────────────────


def refresh_universe() -> None:
    """Fetch S&P 500 constituents and upsert into the universe table."""
    try:
        from backend.data.universe import fetch_sp500_constituents

        df = fetch_sp500_constituents()
        if df.empty:
            logger.warning("DataRefresh: empty S&P 500 fetch, skipping universe update")
            return

        now = datetime.now(UTC).isoformat()
        rows = [
            {
                "ticker": row["ticker"],
                "name": row.get("name", ""),
                "sector": row.get("sector", ""),
                "sub_industry": row.get("sub_industry", ""),
                "fetched_at": now,
            }
            for _, row in df.iterrows()
        ]

        _upsert_with_retry("universe", rows, on_conflict="ticker")

        logger.info("DataRefresh: universe updated — %d constituents", len(rows))
    except Exception:
        logger.exception("DataRefresh: universe refresh failed")


# ── Market Prices (OHLCV) ───────────────────────────────────


def refresh_market_prices() -> None:
    """Batch fetch daily OHLCV for the full universe + cross-asset instruments."""
    from backend.data.cross_asset import CROSS_ASSET_TICKERS, SECTOR_ETFS

    tickers = _get_universe_tickers()
    if not tickers:
        logger.warning("DataRefresh: no tickers in universe, skipping market prices")
        return

    cross_asset_tickers = list(CROSS_ASSET_TICKERS.values()) + list(SECTOR_ETFS.values())
    all_tickers = list(set(tickers + cross_asset_tickers))

    try:
        all_data = yfinance_source.get_multiple_ohlcv(all_tickers, period="5d")
        now = datetime.now(UTC).isoformat()
        total = 0

        for ticker, df in all_data.items():
            if df.empty:
                continue
            rows = []
            for idx, row in df.iterrows():
                price_date = idx.date() if hasattr(idx, "date") else idx
                rows.append(
                    {
                        "ticker": ticker,
                        "price_date": str(price_date),
                        "open": round(float(row.get("Open", 0)), 4) if pd.notna(row.get("Open")) else None,
                        "high": round(float(row.get("High", 0)), 4) if pd.notna(row.get("High")) else None,
                        "low": round(float(row.get("Low", 0)), 4) if pd.notna(row.get("Low")) else None,
                        "close": round(float(row.get("Close", 0)), 4) if pd.notna(row.get("Close")) else None,
                        "volume": int(row.get("Volume", 0)) if pd.notna(row.get("Volume")) else None,
                        "source": "yfinance",
                        "fetched_at": now,
                    }
                )
            if rows:
                _upsert_with_retry("market_prices", rows, on_conflict="ticker,price_date")
                total += len(rows)

        logger.info("DataRefresh: market prices updated — %d rows for %d tickers", total, len(all_data))
    except Exception:
        logger.exception("DataRefresh: market prices refresh failed")


# ── Cross-Asset Prices ──────────────────────────────────────


def refresh_cross_asset_prices() -> None:
    """Fetch cross-asset instrument prices (VIX, yields, commodities, etc.)."""
    from backend.data.cross_asset import CROSS_ASSET_TICKERS, SECTOR_ETFS

    all_symbols = list(CROSS_ASSET_TICKERS.values()) + list(SECTOR_ETFS.values())

    try:
        data = yfinance_source.get_multiple_ohlcv(all_symbols, period="5d")
        now = datetime.now(UTC).isoformat()
        total = 0

        for symbol, df in data.items():
            if df.empty:
                continue
            rows = []
            for idx, row in df.iterrows():
                price_date = idx.date() if hasattr(idx, "date") else idx
                rows.append(
                    {
                        "symbol": symbol,
                        "price_date": str(price_date),
                        "close": round(float(row.get("Close", 0)), 4) if pd.notna(row.get("Close")) else None,
                        "fetched_at": now,
                    }
                )
            if rows:
                _upsert_with_retry("cross_asset_prices", rows, on_conflict="symbol,price_date")
                total += len(rows)

        logger.info("DataRefresh: cross-asset prices updated — %d rows for %d instruments", total, len(data))
    except Exception:
        logger.exception("DataRefresh: cross-asset prices refresh failed")


# ── Fundamentals ────────────────────────────────────────────


def _fetch_dcf_fair_value(ticker: str) -> tuple[float | None, str | None]:
    """Best-effort DCF fair value: FMP API > analyst_target (already in data)."""
    if settings.fmp_api_key:
        try:
            from backend.data.sources.fmp_src import fmp_source

            dcf = fmp_source.get_dcf(ticker)
            if dcf and dcf.get("dcf") and dcf["dcf"] > 0:
                return float(dcf["dcf"]), "fmp_dcf"
        except Exception:
            pass
    return None, None


def refresh_fundamentals() -> None:
    """Fetch fundamentals + DCF fair values for all universe tickers."""
    tickers = _get_universe_tickers()
    if not tickers:
        return

    get_supabase()
    now = datetime.now(UTC).isoformat()
    updated = 0

    for ticker in tickers:
        try:
            data = {}
            if settings.fmp_api_key:
                try:
                    from backend.data.sources.fmp_src import fmp_source

                    data = fmp_source.get_fundamentals(ticker)
                except Exception:
                    pass

            if not data:
                data = yfinance_source.get_fundamentals(ticker)

            if data:
                rev_g = data.get("revenue_growth")
                if isinstance(rev_g, (int, float)) and (rev_g > 1.0 or rev_g < -0.5):
                    rev_g = None

                dcf_val, dcf_method = _fetch_dcf_fair_value(ticker)

                row = {
                    "ticker": ticker,
                    "market_cap": data.get("market_cap"),
                    "pe_ratio": data.get("pe_ratio"),
                    "forward_pe": data.get("forward_pe"),
                    "eps": data.get("eps_trailing") or data.get("eps"),
                    "revenue_growth": rev_g,
                    "profit_margin": data.get("profit_margin"),
                    "sector": data.get("sector"),
                    "industry": data.get("industry"),
                    "avg_volume": data.get("avg_volume"),
                    "shares_outstanding": data.get("shares_outstanding"),
                    "analyst_target": data.get("analyst_target"),
                    "dcf_fair_value": dcf_val,
                    "dcf_method": dcf_method,
                    "fetched_at": now,
                }
                _upsert_with_retry("fundamentals", [row], on_conflict="ticker")
                updated += 1
        except Exception:
            logger.debug("DataRefresh: fundamentals failed for %s", ticker)

    logger.info("DataRefresh: fundamentals updated — %d tickers", updated)


# ── Earnings Data ───────────────────────────────────────────


def refresh_earnings() -> None:
    """Fetch earnings history for universe tickers.

    Primary: FMP (when API key set). Fallback: yfinance earnings_dates.
    """
    tickers = _get_universe_tickers()
    if not tickers:
        return

    get_supabase()
    now = datetime.now(UTC).isoformat()
    updated = 0

    fmp_source = None
    if settings.fmp_api_key:
        try:
            from backend.data.sources.fmp_src import fmp_source as _fmp

            fmp_source = _fmp
        except Exception:
            pass

    for ticker in tickers:
        try:
            earnings: list[dict] = []

            earnings = yfinance_source.get_earnings_history(ticker) or []

            if not earnings and fmp_source:
                try:
                    earnings = fmp_source.get_earnings(ticker) or []
                except Exception:
                    pass

            if not earnings:
                continue

            rows = []
            for e in earnings[:8]:
                report_date = e.get("date") or e.get("report_date")
                if not report_date:
                    continue
                rows.append(
                    {
                        "ticker": ticker,
                        "report_date": str(report_date),
                        "fiscal_quarter": e.get("fiscal_quarter", ""),
                        "eps_actual": e.get("eps_actual") or e.get("actualEarningResult"),
                        "eps_estimate": e.get("eps_estimate") or e.get("estimatedEarning"),
                        "surprise_pct": e.get("surprise_pct") or e.get("surprisePercent"),
                        "revenue_actual": e.get("revenue_actual") or e.get("actualRevenue"),
                        "revenue_estimate": e.get("revenue_estimate") or e.get("estimatedRevenue"),
                        "fetched_at": now,
                    }
                )
            if rows:
                _upsert_with_retry("earnings_data", rows, on_conflict="ticker,report_date")
                updated += 1
        except Exception:
            logger.debug("DataRefresh: earnings failed for %s", ticker)

    logger.info("DataRefresh: earnings updated — %d tickers", updated)


# ── Analyst Revisions ───────────────────────────────────────


def refresh_revisions() -> None:
    """Fetch analyst revisions for universe tickers.

    Primary: yfinance upgrades_downgrades (free).
    Fallback: Finnhub (when API key set).
    """
    tickers = _get_universe_tickers()
    if not tickers:
        return

    sb = get_supabase()
    now = datetime.now(UTC).isoformat()
    updated = 0

    finnhub_source = None
    if settings.finnhub_api_key:
        try:
            from backend.data.sources.finnhub_src import finnhub_source as _fh

            finnhub_source = _fh
        except Exception:
            pass

    for ticker in tickers:
        try:
            revisions: list[dict] = []

            revisions = yfinance_source.get_analyst_revisions(ticker, limit=10)

            if not revisions and finnhub_source:
                try:
                    data = finnhub_source.get_analyst_revisions(ticker)
                    if data and data.get("revisions"):
                        revisions = data["revisions"][:10]
                except Exception:
                    pass

            if not revisions:
                continue

            rows = []
            for rev in revisions:
                rev_date = rev.get("date") or rev.get("revision_date")
                if not rev_date:
                    continue
                rows.append(
                    {
                        "ticker": ticker,
                        "revision_date": str(rev_date),
                        "firm": rev.get("firm", ""),
                        "action": rev.get("action", ""),
                        "rating_from": rev.get("from_grade", ""),
                        "rating_to": rev.get("to_grade", ""),
                        "price_target": rev.get("price_target"),
                        "fetched_at": now,
                    }
                )
            if rows:
                sb.table("analyst_revisions").insert(rows).execute()
                updated += 1
        except Exception:
            logger.debug("DataRefresh: revisions failed for %s", ticker)

    logger.info("DataRefresh: revisions updated — %d tickers", updated)


# ── News Sentiment ──────────────────────────────────────────

STRONG_POS = 0.6
STRONG_NEG = -0.3


def _fetch_yfinance_headlines(ticker: str) -> list[str]:
    """Pull recent news headlines from yfinance (free, no API key)."""
    try:
        import yfinance as yf

        t = yf.Ticker(ticker)
        headlines: list[str] = []
        for item in (t.news or [])[:20]:
            title = item.get("title", "")
            if not title:
                content = item.get("content", {})
                if isinstance(content, dict):
                    title = content.get("title", "")
            if title:
                headlines.append(title)
        return headlines
    except Exception as e:
        logger.debug("yfinance news fetch failed for %s: %s", ticker, e)
        return []


def refresh_news_sentiment() -> None:
    """Fetch yfinance news, score with FinBERT, and populate the sentiment cache.

    Runs every 2 hours. Uses FinBERT (GPU/CPU) with VADER fallback.
    No paid API key required — yfinance news is free.
    """
    from backend.data.sentiment_cache import CachedSentiment, sentiment_cache
    from nlp.finbert_sentiment import get_analyzer

    tickers = _get_universe_tickers()
    if not tickers:
        return

    analyzer = get_analyzer(use_finbert=True)
    sb = get_supabase()
    now = datetime.now(UTC).isoformat()
    updated = 0
    cache_entries: list[CachedSentiment] = []

    for ticker in tickers:
        try:
            headlines = _fetch_yfinance_headlines(ticker)
            if not headlines:
                continue

            results = analyzer.analyze_batch(headlines)
            n = len(results)
            avg_compound = sum(r.compound for r in results) / n

            sum(1 for r in results if r.label == "positive")
            sum(1 for r in results if r.label == "negative")

            if avg_compound >= STRONG_POS:
                label = "bullish"
            elif avg_compound <= STRONG_NEG:
                label = "bearish"
            else:
                label = "neutral"

            composite = max(0.0, min(100.0, 50.0 + avg_compound * 50.0))

            cache_entries.append(
                CachedSentiment(
                    ticker=ticker,
                    composite_score=round(composite, 2),
                    sentiment_label=label,
                    avg_compound=round(avg_compound, 4),
                    article_count=n,
                    model_used=results[0].model if results else "none",
                )
            )

            rows = []
            for r in results:
                rows.append(
                    {
                        "ticker": ticker,
                        "headline": r.text[:500],
                        "source_name": "yfinance",
                        "published_at": now,
                        "sentiment_score": round(r.compound, 4),
                        "sentiment_label": r.label,
                        "fetched_at": now,
                    }
                )
            if rows:
                sb.table("news_sentiment").insert(rows).execute()

            updated += 1
        except Exception:
            logger.debug("DataRefresh: news failed for %s", ticker)

    sentiment_cache.put_batch(cache_entries)
    logger.info(
        "DataRefresh: news sentiment updated — %d tickers, %d cached",
        updated,
        len(cache_entries),
    )


# ── Options Flow ────────────────────────────────────────────


def refresh_options_flow() -> None:
    """Fetch institutional options flow from SteadyAPI."""
    if not settings.enable_steadyapi or not settings.steadyapi_api_key:
        return

    try:
        from backend.data.sources.steadyapi_src import steadyapi_source

        sweeps = steadyapi_source.get_institutional_sweeps()
        if not sweeps:
            return

        sb = get_supabase()
        now = datetime.now(UTC).isoformat()
        rows = []
        for s in sweeps[:100]:
            rows.append(
                {
                    "ticker": s.get("ticker", s.get("symbol", "")),
                    "flow_timestamp": s.get("timestamp") or s.get("date") or now,
                    "flow_type": s.get("type", "sweep"),
                    "side": s.get("side", s.get("call_put", "")),
                    "strike": s.get("strike"),
                    "expiry": s.get("expiry") or s.get("expiration_date"),
                    "premium": s.get("premium") or s.get("total_premium"),
                    "volume": s.get("volume"),
                    "open_interest": s.get("open_interest"),
                    "fetched_at": now,
                }
            )

        if rows:
            for i in range(0, len(rows), BATCH_SIZE):
                batch = rows[i : i + BATCH_SIZE]
                sb.table("options_flow").insert(batch).execute()

        logger.info("DataRefresh: options flow updated — %d records", len(rows))
    except Exception:
        logger.exception("DataRefresh: options flow refresh failed")


# ── Dark Pool ───────────────────────────────────────────────


def refresh_dark_pool() -> None:
    """Fetch short volume / dark pool data for universe tickers.

    Primary: Polygon short volume API (daily FINRA data, reliable for S&P 500).
    Fallback: FINRA ATS direct (limited to OTC stocks).
    """
    tickers = _get_universe_tickers()
    if not tickers:
        return

    sb = get_supabase()
    now = datetime.now(UTC).isoformat()
    updated = 0

    use_polygon = settings.enable_polygon and settings.polygon_api_key

    for ticker in tickers:
        try:
            if use_polygon:
                from backend.data.sources.polygon_src import polygon_source

                records = polygon_source.get_short_volume(ticker, limit=5)
                if records:
                    latest = records[0]
                    row = {
                        "ticker": ticker,
                        "report_date": latest["date"],
                        "volume": int(latest.get("total_volume") or 0),
                        "short_volume": int(latest.get("short_volume") or 0),
                        "short_ratio": latest.get("short_ratio"),
                        "fetched_at": now,
                    }
                    sb.table("dark_pool").upsert(
                        row,
                        on_conflict="ticker,report_date",
                    ).execute()
                    updated += 1
                    continue

            from backend.data.sources.finra_src import finra_source

            data = finra_source.compute_dark_pool_metrics(ticker)
            if not data or data.get("signal_score", 0) == 0:
                continue

            row = {
                "ticker": ticker,
                "report_date": str(date.today()),
                "volume": data.get("total_volume"),
                "short_volume": data.get("short_volume"),
                "short_ratio": data.get("short_ratio"),
                "fetched_at": now,
            }
            sb.table("dark_pool").upsert(row, on_conflict="ticker,report_date").execute()
            updated += 1
        except Exception:
            logger.debug("DataRefresh: dark pool failed for %s", ticker)

    logger.info("DataRefresh: dark pool updated — %d tickers", updated)


# ── Insider Trades ──────────────────────────────────────────


def refresh_insider_trades() -> None:
    """Fetch insider trades from SEC EDGAR for universe tickers."""
    if not settings.sec_edgar_email:
        return

    tickers = _get_universe_tickers()
    if not tickers:
        return

    sb = get_supabase()
    now = datetime.now(UTC).isoformat()
    updated = 0

    try:
        from backend.data.sources.edgar_src import edgar_source
    except Exception:
        return

    for ticker in tickers[:100]:
        try:
            trades = edgar_source.get_insider_trades(ticker, days_back=90)
            if not trades:
                continue
            rows = []
            for t in trades[:20]:
                rows.append(
                    {
                        "ticker": ticker,
                        "insider_name": t.get("insider_name", ""),
                        "title": t.get("title", ""),
                        "transaction_date": t.get("transaction_date") or t.get("date"),
                        "transaction_type": t.get("transaction_type", ""),
                        "shares": t.get("shares"),
                        "price": t.get("price"),
                        "value": t.get("value"),
                        "fetched_at": now,
                    }
                )
            if rows:
                sb.table("insider_trades").insert(rows).execute()
                updated += 1
        except Exception:
            logger.debug("DataRefresh: insider trades failed for %s", ticker)

    logger.info("DataRefresh: insider trades updated — %d tickers", updated)


# ── Data Retention Cleanup ──────────────────────────────────


def cleanup_old_data() -> None:
    """Remove old data to prevent unbounded DB growth."""
    sb = get_supabase()
    now = date.today()

    retention_rules = {
        "market_prices": ("price_date", 730),
        "cross_asset_prices": ("price_date", 730),
        "news_sentiment": ("fetched_at", 90),
        "options_flow": ("fetched_at", 30),
        "analyst_revisions": ("fetched_at", 365),
        "insider_trades": ("fetched_at", 365),
        "dark_pool": ("report_date", 365),
        "earnings_data": ("fetched_at", 730),
    }

    for table, (date_col, days) in retention_rules.items():
        cutoff = str(now - timedelta(days=days))
        try:
            sb.table(table).delete().lt(date_col, cutoff).execute()
        except Exception:
            logger.debug("DataRefresh: cleanup failed for %s", table)

    logger.info("DataRefresh: old data cleanup complete")


# ── Full Initial Load ───────────────────────────────────────


def initial_data_load() -> None:
    """Run on first startup to populate all tables. Runs in a background thread."""
    logger.info("DataRefresh: starting initial data load...")

    refresh_universe()
    refresh_market_prices()
    refresh_cross_asset_prices()
    refresh_fundamentals()

    refresh_earnings()
    refresh_news_sentiment()
    refresh_revisions()
    if settings.enable_steadyapi and settings.steadyapi_api_key:
        refresh_options_flow()
    if settings.sec_edgar_email:
        refresh_insider_trades()

    refresh_dark_pool()

    logger.info("DataRefresh: initial data load complete")

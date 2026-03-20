"""Multi-source data orchestrator — reads from Supabase pre-fetch tables first.

Priority: Supabase structured tables → paid API → yfinance (free fallback).
The background refresh scheduler keeps tables populated; this module reads them.
"""

import logging
from datetime import UTC, date, datetime, timedelta

import pandas as pd

from backend.config import settings
from backend.data.sources.yfinance_src import yfinance_source
from backend.models.database import get_supabase

logger = logging.getLogger(__name__)


class DataFetcher:
    """Multi-source data orchestrator with DB-first reads and API fallback."""

    # ── OHLCV ───────────────────────────────────────────────────

    _MIN_OHLCV_ROWS = {
        "5d": 2,
        "1mo": 10,
        "3mo": 30,
        "6mo": 60,
        "1y": 100,
        "2y": 200,
        "5y": 500,
        "max": 500,
    }

    def get_daily_ohlcv(
        self,
        ticker: str,
        period: str = "2y",
        live: bool = False,
    ) -> pd.DataFrame:
        if not live:
            df = self._read_ohlcv_from_db(ticker, period)
            min_rows = self._MIN_OHLCV_ROWS.get(period, 60)
            if not df.empty and len(df) >= min_rows:
                return df
            if not df.empty:
                logger.debug(
                    "DB has %d rows for %s (need %d for %s), falling through to API",
                    len(df),
                    ticker,
                    min_rows,
                    period,
                )

        df = pd.DataFrame()

        if settings.enable_polygon and settings.polygon_api_key:
            try:
                from backend.data.sources.polygon_src import polygon_source

                df = polygon_source.get_daily_ohlcv(ticker, period=period)
            except Exception:
                logger.warning("Polygon fetch failed for %s, falling back", ticker)

        if df.empty:
            df = yfinance_source.get_daily_ohlcv(ticker, period=period)

        return df

    def _read_ohlcv_from_db(self, ticker: str, period: str) -> pd.DataFrame:
        """Read OHLCV from the market_prices table and return as DataFrame."""
        try:
            days = self._period_to_days(period)
            cutoff = str(date.today() - timedelta(days=days))

            sb = get_supabase()
            result = (
                sb.table("market_prices")
                .select("price_date,open,high,low,close,volume")
                .eq("ticker", ticker)
                .gte("price_date", cutoff)
                .order("price_date")
                .execute()
            )

            if not result.data:
                return pd.DataFrame()

            df = pd.DataFrame(result.data)
            df["price_date"] = pd.to_datetime(df["price_date"])
            df = df.set_index("price_date")
            df.index.name = "Date"
            df.columns = ["Open", "High", "Low", "Close", "Volume"]
            df = df.dropna(subset=["Close"])
            return df
        except Exception:
            logger.debug("DB read failed for OHLCV %s, will use API", ticker)
            return pd.DataFrame()

    def get_multiple_ohlcv(self, tickers: list[str], period: str = "2y") -> dict[str, pd.DataFrame]:
        result = {}
        min_rows = self._MIN_OHLCV_ROWS.get(period, 60)
        for ticker in tickers:
            df = self._read_ohlcv_from_db(ticker, period)
            if not df.empty and len(df) >= min_rows:
                result[ticker] = df

        missing = [t for t in tickers if t not in result]
        if missing:
            api_data = yfinance_source.get_multiple_ohlcv(missing, period=period)
            result.update(api_data)

        return result

    def get_current_price(self, ticker: str, live: bool = False) -> float | None:
        """Hybrid approach: live fetch for single-ticker views, DB for bulk.

        Set live=True for analysis pages / active trade monitoring.
        Default (live=False) reads from the market_prices table.
        """
        if live:
            return yfinance_source.get_current_price(ticker)

        try:
            sb = get_supabase()
            result = (
                sb.table("market_prices")
                .select("close")
                .eq("ticker", ticker)
                .order("price_date", desc=True)
                .limit(1)
                .execute()
            )
            if result.data and result.data[0].get("close"):
                return float(result.data[0]["close"])
        except Exception:
            pass

        return yfinance_source.get_current_price(ticker)

    # ── Fundamentals ────────────────────────────────────────────

    _FUNDAMENTALS_CRITICAL_KEYS = {
        "pe_ratio",
        "forward_pe",
        "peg_ratio",
        "revenue_growth",
        "profit_margin",
        "debt_to_equity",
        "eps_trailing",
        "eps_forward",
    }

    def get_fundamentals(self, ticker: str) -> dict:
        db_data: dict = {}
        try:
            sb = get_supabase()
            result = sb.table("fundamentals").select("*").eq("ticker", ticker).execute()
            if result.data:
                row = result.data[0]
                row.pop("id", None)
                row.pop("fetched_at", None)
                db_data = {k: v for k, v in row.items() if v is not None}
                if "eps" in db_data:
                    db_data.setdefault("eps_trailing", db_data.pop("eps"))
                rg = db_data.get("revenue_growth")
                if isinstance(rg, (int, float)) and (rg > 1.0 or rg < -0.5):
                    db_data.pop("revenue_growth")
        except Exception:
            pass

        has_critical = db_data and any(db_data.get(k) is not None for k in self._FUNDAMENTALS_CRITICAL_KEYS)
        if has_critical:
            missing = [k for k in self._FUNDAMENTALS_CRITICAL_KEYS if db_data.get(k) is None]
            if missing:
                live = yfinance_source.get_fundamentals(ticker)
                for k in missing:
                    if live.get(k) is not None:
                        db_data[k] = live[k]
            return db_data

        if db_data:
            live = yfinance_source.get_fundamentals(ticker)
            live.update({k: v for k, v in db_data.items() if v is not None})
            return live

        data: dict = {}
        if settings.fmp_api_key:
            try:
                from backend.data.sources.fmp_src import fmp_source

                data = fmp_source.get_fundamentals(ticker)
            except Exception:
                logger.warning("FMP fetch failed for %s, falling back", ticker)

        if not data:
            data = yfinance_source.get_fundamentals(ticker)

        return data

    def get_cashflow(self, ticker: str) -> pd.DataFrame:
        """Annual cash flow statement. Not DB-cached (complex DataFrame index)."""
        return yfinance_source.get_cashflow(ticker)

    def get_shares_outstanding(self, ticker: str) -> int | None:
        try:
            sb = get_supabase()
            result = sb.table("fundamentals").select("shares_outstanding").eq("ticker", ticker).execute()
            if result.data and result.data[0].get("shares_outstanding"):
                return int(result.data[0]["shares_outstanding"])
        except Exception:
            pass
        return yfinance_source.get_shares_outstanding(ticker)

    # ── Earnings ────────────────────────────────────────────────

    def get_earnings_data(self, ticker: str) -> list[dict]:
        try:
            sb = get_supabase()
            result = (
                sb.table("earnings_data")
                .select("*")
                .eq("ticker", ticker)
                .order("report_date", desc=True)
                .limit(8)
                .execute()
            )
            if result.data:
                return result.data
        except Exception:
            pass

        if settings.fmp_api_key:
            try:
                from backend.data.sources.fmp_src import fmp_source

                data = fmp_source.get_earnings(ticker)
                if data:
                    return data
            except Exception:
                logger.warning("FMP earnings fetch failed for %s", ticker)

        return yfinance_source.get_earnings_history(ticker)

    # ── Analyst Revisions ───────────────────────────────────────

    def get_analyst_revisions(self, ticker: str) -> dict:
        try:
            sb = get_supabase()
            result = (
                sb.table("analyst_revisions")
                .select("*")
                .eq("ticker", ticker)
                .order("revision_date", desc=True)
                .limit(10)
                .execute()
            )
            if result.data:
                return {"revisions": result.data, "ticker": ticker}
        except Exception:
            pass

        if settings.finnhub_api_key:
            try:
                from backend.data.sources.finnhub_src import finnhub_source

                return finnhub_source.get_analyst_revisions(ticker)
            except Exception:
                logger.warning("Finnhub revisions fetch failed for %s", ticker)

        revisions = yfinance_source.get_analyst_revisions(ticker)
        if revisions:
            return {"revisions": revisions, "ticker": ticker}
        return {}

    # ── News / Sentiment ────────────────────────────────────────

    def get_news_sentiment(self, ticker: str) -> list[dict]:
        try:
            sb = get_supabase()
            result = (
                sb.table("news_sentiment")
                .select("*")
                .eq("ticker", ticker)
                .order("published_at", desc=True)
                .limit(20)
                .execute()
            )
            if result.data:
                return result.data
        except Exception:
            pass

        if settings.finnhub_api_key:
            try:
                from backend.data.sources.finnhub_src import finnhub_source

                return finnhub_source.get_news(ticker)
            except Exception:
                logger.warning("Finnhub news fetch failed for %s", ticker)
        return []

    # ── Recommendations ─────────────────────────────────────────

    def get_earnings_calendar(self, from_date: str | None = None, to_date: str | None = None) -> list[dict]:
        if settings.fmp_api_key:
            try:
                from backend.data.sources.fmp_src import fmp_source

                return fmp_source.get_earnings_calendar(from_date, to_date)
            except Exception:
                logger.warning("FMP earnings calendar fetch failed")
        return []

    def get_recommendation_trends(self, ticker: str) -> list[dict]:
        if settings.finnhub_api_key:
            try:
                from backend.data.sources.finnhub_src import finnhub_source

                data = finnhub_source.get_recommendation_trends(ticker)
                if data:
                    return data
            except Exception:
                logger.warning("Finnhub recommendation trends fetch failed for %s", ticker)

        return yfinance_source.get_recommendation_trends(ticker)

    # ── Macro / FRED ────────────────────────────────────────────

    def get_yield_curve_slope(self) -> pd.Series:
        if settings.fred_api_key:
            try:
                from backend.data.sources.fred_src import fred_source

                data = fred_source.get_yield_curve_slope()
                if not data.empty:
                    return data
            except Exception:
                logger.warning("FRED yield curve fetch failed, falling back to yfinance")

        from backend.data.cross_asset import cross_asset_data

        return cross_asset_data.compute_yield_curve_slope()

    def get_credit_spread(self) -> pd.Series:
        if settings.fred_api_key:
            try:
                from backend.data.sources.fred_src import fred_source

                data = fred_source.get_credit_spread()
                if not data.empty:
                    return data
            except Exception:
                logger.warning("FRED credit spread fetch failed, falling back")

        from backend.data.cross_asset import cross_asset_data

        return cross_asset_data.compute_credit_spread()

    # ── Insider Trades / SEC EDGAR ──────────────────────────────

    def get_insider_trades(self, ticker: str, days_back: int = 90) -> list[dict]:
        try:
            cutoff = str(date.today() - timedelta(days=days_back))
            sb = get_supabase()
            result = (
                sb.table("insider_trades")
                .select("*")
                .eq("ticker", ticker)
                .gte("transaction_date", cutoff)
                .order("transaction_date", desc=True)
                .execute()
            )
            if result.data:
                return result.data
        except Exception:
            pass

        if settings.sec_edgar_email:
            try:
                from backend.data.sources.edgar_src import edgar_source

                return edgar_source.get_insider_trades(ticker, days_back=days_back)
            except Exception:
                logger.warning("EDGAR insider trades fetch failed for %s", ticker)
        return []

    def get_insider_buying_score(self, ticker: str) -> dict:
        if settings.sec_edgar_email:
            try:
                from backend.data.sources.edgar_src import edgar_source

                data = edgar_source.score_insider_buying(ticker)
                if data:
                    return data
            except Exception:
                logger.warning("EDGAR insider score failed for %s", ticker)
        return {"signal_score": 0, "transactions": []}

    # ── Dark Pool / FINRA ATS ───────────────────────────────────

    def get_dark_pool_activity(self, ticker: str) -> dict:
        try:
            sb = get_supabase()
            result = (
                sb.table("dark_pool")
                .select("*")
                .eq("ticker", ticker)
                .order("report_date", desc=True)
                .limit(1)
                .execute()
            )
            if result.data:
                row = result.data[0]
                return {
                    "signal_score": 50 if row.get("short_ratio") and row["short_ratio"] > 0.4 else 20,
                    "total_volume": row.get("volume"),
                    "short_volume": row.get("short_volume"),
                    "short_ratio": row.get("short_ratio"),
                }
        except Exception:
            pass

        if settings.enable_polygon and settings.polygon_api_key:
            try:
                from backend.data.sources.polygon_src import polygon_source

                records = polygon_source.get_short_volume(ticker, limit=1)
                if records:
                    r = records[0]
                    return {
                        "signal_score": 50 if r["short_ratio"] > 0.4 else 20,
                        "total_volume": int(r.get("total_volume") or 0),
                        "short_volume": int(r.get("short_volume") or 0),
                        "short_ratio": r.get("short_ratio"),
                    }
            except Exception:
                logger.warning("Polygon short volume fetch failed for %s", ticker)

        try:
            from backend.data.sources.finra_src import finra_source

            return finra_source.compute_dark_pool_metrics(ticker)
        except Exception:
            logger.warning("FINRA dark pool fetch failed for %s", ticker)
        return {"signal_score": 0}

    # ── SteadyAPI Options Flow ──────────────────────────────────

    def get_steadyapi_sweeps(self) -> list[dict]:
        try:
            sb = get_supabase()
            cutoff = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
            result = (
                sb.table("options_flow")
                .select("*")
                .gte("fetched_at", cutoff)
                .order("fetched_at", desc=True)
                .limit(100)
                .execute()
            )
            if result.data:
                return result.data
        except Exception:
            pass

        if not settings.enable_steadyapi or not settings.steadyapi_api_key:
            return []

        try:
            from backend.data.sources.steadyapi_src import steadyapi_source

            return steadyapi_source.get_institutional_sweeps()
        except Exception:
            logger.warning("SteadyAPI sweeps fetch failed")
        return []

    def get_short_interest(self, ticker: str) -> list[dict]:
        if not settings.steadyapi_api_key:
            return []

        try:
            from backend.data.sources.steadyapi_src import steadyapi_source

            return steadyapi_source.get_short_interest(ticker)
        except Exception:
            logger.warning("Short interest fetch failed for %s", ticker)
        return []

    def get_institutional_holdings(self, ticker: str) -> dict:
        if not settings.steadyapi_api_key:
            return {}

        try:
            from backend.data.sources.steadyapi_src import steadyapi_source

            return steadyapi_source.get_institutional_holdings(ticker)
        except Exception:
            logger.warning("Institutional holdings fetch failed for %s", ticker)
        return {}

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _period_to_days(period: str) -> int:
        """Convert yfinance-style period string to days."""
        mapping = {
            "5d": 5,
            "1mo": 30,
            "3mo": 90,
            "6mo": 180,
            "1y": 365,
            "2y": 730,
            "5y": 1825,
            "max": 3650,
        }
        return mapping.get(period, 730)


data_fetcher = DataFetcher()

import logging

import pandas as pd

from backend.config import settings
from backend.data.cache import data_cache
from backend.data.sources.yfinance_src import yfinance_source

logger = logging.getLogger(__name__)


class DataFetcher:
    """Multi-source data orchestrator with caching and fallback.

    Priority order: paid sources (when enabled) → yfinance (free fallback).
    All methods cache results to reduce API calls.
    """

    def get_daily_ohlcv(
        self, ticker: str, period: str = "2y", live: bool = False,
    ) -> pd.DataFrame:
        cache_key = f"ohlcv:{ticker}:{period}"

        if not live:
            cached = data_cache.get(cache_key)
            if cached is not None and isinstance(cached, pd.DataFrame) and not cached.empty:
                return cached

        df = pd.DataFrame()

        if settings.enable_polygon and settings.polygon_api_key:
            try:
                from backend.data.sources.polygon_src import polygon_source
                df = polygon_source.get_daily_ohlcv(ticker, period=period)
            except Exception:
                logger.warning("Polygon fetch failed for %s, falling back", ticker)

        if df.empty:
            df = yfinance_source.get_daily_ohlcv(ticker, period=period)

        if not df.empty:
            data_cache.set(cache_key, df, ttl_hours=1.0)
        return df

    def get_multiple_ohlcv(self, tickers: list[str], period: str = "2y") -> dict[str, pd.DataFrame]:
        return yfinance_source.get_multiple_ohlcv(tickers, period=period)

    def get_current_price(self, ticker: str) -> float | None:
        return yfinance_source.get_current_price(ticker)

    def get_fundamentals(self, ticker: str) -> dict:
        cache_key = f"fundamentals:{ticker}"
        cached = data_cache.get(cache_key)
        if cached is not None and isinstance(cached, dict):
            return cached

        data = {}

        if settings.fmp_api_key:
            try:
                from backend.data.sources.fmp_src import fmp_source
                data = fmp_source.get_fundamentals(ticker)
            except Exception:
                logger.warning("FMP fetch failed for %s, falling back", ticker)

        if not data:
            data = yfinance_source.get_fundamentals(ticker)

        if data:
            data_cache.set(cache_key, data, ttl_hours=24.0)
        return data

    def get_cashflow(self, ticker: str) -> pd.DataFrame:
        """Annual cash flow statement. FMP if available, else yfinance.

        Not DB-cached because the DataFrame has complex index labels that
        don't survive JSON round-tripping. Called once per analysis anyway.
        """
        return yfinance_source.get_cashflow(ticker)

    def get_shares_outstanding(self, ticker: str) -> int | None:
        """Shares outstanding for per-share calculations."""
        return yfinance_source.get_shares_outstanding(ticker)

    def get_earnings_data(self, ticker: str) -> list[dict]:
        cache_key = f"earnings:{ticker}"
        cached = data_cache.get(cache_key)
        if cached is not None and isinstance(cached, (dict, list)):
            return cached if isinstance(cached, list) else [cached] if cached else []

        if settings.fmp_api_key:
            try:
                from backend.data.sources.fmp_src import fmp_source
                data = fmp_source.get_earnings(ticker)
                if data:
                    data_cache.set(cache_key, data, ttl_hours=24.0)
                    return data
            except Exception:
                logger.warning("FMP earnings fetch failed for %s", ticker)

        return []

    def get_analyst_revisions(self, ticker: str) -> dict:
        if settings.finnhub_api_key:
            try:
                from backend.data.sources.finnhub_src import finnhub_source
                return finnhub_source.get_analyst_revisions(ticker)
            except Exception:
                logger.warning("Finnhub revisions fetch failed for %s", ticker)
        return {}

    def get_news_sentiment(self, ticker: str) -> list[dict]:
        if settings.finnhub_api_key:
            try:
                from backend.data.sources.finnhub_src import finnhub_source
                return finnhub_source.get_news(ticker)
            except Exception:
                logger.warning("Finnhub news fetch failed for %s", ticker)
        return []

    def get_options_flow(self, ticker: str) -> dict:
        if settings.enable_smart_money and settings.uw_api_key:
            try:
                from backend.data.sources.unusual_whales_src import uw_source
                return uw_source.get_options_flow(ticker)
            except Exception:
                logger.warning("Unusual Whales flow fetch failed for %s", ticker)
        return {}

    def get_dark_pool(self, ticker: str) -> dict:
        if settings.enable_smart_money and settings.uw_api_key:
            try:
                from backend.data.sources.unusual_whales_src import uw_source
                return uw_source.get_dark_pool(ticker)
            except Exception:
                logger.warning("Unusual Whales dark pool fetch failed for %s", ticker)
        return {}

    def get_earnings_calendar(
        self, from_date: str | None = None, to_date: str | None = None
    ) -> list[dict]:
        """Upcoming earnings dates from FMP (when key is set)."""
        if settings.fmp_api_key:
            try:
                from backend.data.sources.fmp_src import fmp_source
                return fmp_source.get_earnings_calendar(from_date, to_date)
            except Exception:
                logger.warning("FMP earnings calendar fetch failed")
        return []

    def get_earnings_surprises(self, ticker: str) -> list[dict]:
        """Historical EPS surprises, preferring Finnhub > FMP > yfinance."""
        if settings.finnhub_api_key:
            try:
                from backend.data.sources.finnhub_src import finnhub_source
                data = finnhub_source.get_earnings_surprises(ticker)
                if data:
                    return data
            except Exception:
                logger.warning("Finnhub earnings surprises fetch failed for %s", ticker)

        if settings.fmp_api_key:
            try:
                from backend.data.sources.fmp_src import fmp_source
                data = fmp_source.get_eps_surprises(ticker)
                if data:
                    return data
            except Exception:
                logger.warning("FMP EPS surprises fetch failed for %s", ticker)

        return yfinance_source.get_earnings_history(ticker)

    def get_recommendation_trends(self, ticker: str) -> list[dict]:
        """Analyst recommendation trends, preferring Finnhub > yfinance."""
        if settings.finnhub_api_key:
            try:
                from backend.data.sources.finnhub_src import finnhub_source
                data = finnhub_source.get_recommendation_trends(ticker)
                if data:
                    return data
            except Exception:
                logger.warning("Finnhub recommendation trends fetch failed for %s", ticker)

        return yfinance_source.get_recommendation_trends(ticker)

    # ── Macro / FRED ───────────────────────────────────────────

    def get_yield_curve_slope(self) -> pd.Series:
        """10Y-2Y yield spread from FRED (precise) or yfinance (fallback)."""
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
        """High-yield OAS from FRED or HYG/LQD ratio fallback."""
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

    def get_macro_snapshot(self) -> dict[str, float | None]:
        """Latest macro indicators from FRED (empty dict if no key)."""
        if settings.fred_api_key:
            try:
                from backend.data.sources.fred_src import fred_source
                return fred_source.get_macro_snapshot()
            except Exception:
                logger.warning("FRED macro snapshot fetch failed")
        return {}

    # ── Insider Trades / SEC EDGAR ─────────────────────────────

    def get_insider_trades(self, ticker: str, days_back: int = 90) -> list[dict]:
        """Insider transactions from SEC EDGAR Form 4 filings."""
        cache_key = f"insider_trades:{ticker}"
        cached = data_cache.get(cache_key)
        if cached is not None and isinstance(cached, list):
            return cached

        if settings.sec_edgar_email:
            try:
                from backend.data.sources.edgar_src import edgar_source
                data = edgar_source.get_insider_trades(ticker, days_back=days_back)
                if data:
                    data_cache.set(cache_key, data, ttl_hours=24.0)
                return data
            except Exception:
                logger.warning("EDGAR insider trades fetch failed for %s", ticker)
        return []

    def get_insider_buying_score(self, ticker: str) -> dict:
        """Composite insider buying signal from SEC EDGAR."""
        cache_key = f"insider_score:{ticker}"
        cached = data_cache.get(cache_key)
        if cached is not None and isinstance(cached, dict):
            return cached

        if settings.sec_edgar_email:
            try:
                from backend.data.sources.edgar_src import edgar_source
                data = edgar_source.score_insider_buying(ticker)
                if data:
                    data_cache.set(cache_key, data, ttl_hours=24.0)
                return data
            except Exception:
                logger.warning("EDGAR insider score failed for %s", ticker)
        return {"signal_score": 0, "transactions": []}

    # ── Dark Pool / FINRA ATS ──────────────────────────────────

    def get_dark_pool_activity(self, ticker: str) -> dict:
        """Dark pool accumulation metrics from FINRA ATS data."""
        cache_key = f"dark_pool_activity:{ticker}"
        cached = data_cache.get(cache_key)
        if cached is not None and isinstance(cached, dict):
            return cached

        try:
            from backend.data.sources.finra_src import finra_source
            data = finra_source.compute_dark_pool_metrics(ticker)
            if data and data.get("signal_score", 0) > 0:
                data_cache.set(cache_key, data, ttl_hours=24.0)
            return data
        except Exception:
            logger.warning("FINRA dark pool fetch failed for %s", ticker)
        return {"signal_score": 0}

    # ── SteadyAPI Options Flow ─────────────────────────────────

    def get_steadyapi_flow(self, ticker: str | None = None) -> list[dict]:
        """Institutional options flow from SteadyAPI.

        If ticker is provided, filters to that ticker only.
        Otherwise returns all recent flow.
        """
        if not settings.enable_steadyapi or not settings.steadyapi_api_key:
            return []

        try:
            from backend.data.sources.steadyapi_src import steadyapi_source
            if ticker:
                return steadyapi_source.get_flow_for_ticker(ticker)
            return steadyapi_source.get_options_flow()
        except Exception:
            logger.warning("SteadyAPI flow fetch failed")
        return []

    def get_steadyapi_sweeps(self) -> list[dict]:
        """Institutional sweep orders from SteadyAPI (strongest flow signal)."""
        if not settings.enable_steadyapi or not settings.steadyapi_api_key:
            return []

        try:
            from backend.data.sources.steadyapi_src import steadyapi_source
            return steadyapi_source.get_institutional_sweeps()
        except Exception:
            logger.warning("SteadyAPI sweeps fetch failed")
        return []


data_fetcher = DataFetcher()

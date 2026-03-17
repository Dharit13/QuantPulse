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

    def get_daily_ohlcv(self, ticker: str, period: str = "2y") -> pd.DataFrame:
        cache_key = f"ohlcv:{ticker}:{period}"
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

    def get_earnings_data(self, ticker: str) -> dict:
        cache_key = f"earnings:{ticker}"
        cached = data_cache.get(cache_key)
        if cached is not None and isinstance(cached, dict):
            return cached

        if settings.fmp_api_key:
            try:
                from backend.data.sources.fmp_src import fmp_source
                data = fmp_source.get_earnings(ticker)
                if data:
                    data_cache.set(cache_key, data, ttl_hours=24.0)
                    return data
            except Exception:
                logger.warning("FMP earnings fetch failed for %s", ticker)

        return {}

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


data_fetcher = DataFetcher()

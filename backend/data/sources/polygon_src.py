"""Polygon.io data source stub.

Enable by setting ENABLE_POLYGON=true and POLYGON_API_KEY in .env.
Provides: real-time prices, 1-min intraday bars, options chain + OI.
"""

import logging

import pandas as pd

from backend.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.polygon.io"


class PolygonSource:
    def __init__(self):
        self.api_key = settings.polygon_api_key

    def get_daily_ohlcv(self, ticker: str, period: str = "2y") -> pd.DataFrame:
        # TODO: implement when Polygon API key is available
        logger.info("Polygon daily OHLCV not yet implemented for %s", ticker)
        return pd.DataFrame()

    def get_intraday_bars(self, ticker: str, interval: str = "1min", days_back: int = 5) -> pd.DataFrame:
        logger.info("Polygon intraday bars not yet implemented for %s", ticker)
        return pd.DataFrame()

    def get_options_chain(self, ticker: str) -> dict:
        logger.info("Polygon options chain not yet implemented for %s", ticker)
        return {}


polygon_source = PolygonSource()

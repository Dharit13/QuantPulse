"""Financial Modeling Prep data source stub.

Enable by setting FMP_API_KEY in .env.
Provides: earnings calendar, EPS estimates, fundamentals, analyst data.
"""

import logging

import pandas as pd

from backend.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://financialmodelingprep.com/api/v3"


class FMPSource:
    def __init__(self):
        self.api_key = settings.fmp_api_key

    def get_fundamentals(self, ticker: str) -> dict:
        logger.info("FMP fundamentals not yet implemented for %s", ticker)
        return {}

    def get_earnings(self, ticker: str) -> dict:
        logger.info("FMP earnings not yet implemented for %s", ticker)
        return {}

    def get_earnings_calendar(self, from_date: str, to_date: str) -> list[dict]:
        logger.info("FMP earnings calendar not yet implemented")
        return []

    def get_analyst_estimates(self, ticker: str) -> list[dict]:
        logger.info("FMP analyst estimates not yet implemented for %s", ticker)
        return []

    def get_eps_surprises(self, ticker: str) -> list[dict]:
        logger.info("FMP EPS surprises not yet implemented for %s", ticker)
        return []


fmp_source = FMPSource()

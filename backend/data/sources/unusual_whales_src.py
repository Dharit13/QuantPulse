"""Unusual Whales data source stub.

Enable by setting ENABLE_SMART_MONEY=true and UW_API_KEY in .env.
Provides: options flow, dark pool prints, institutional holdings, congress trades.
"""

import logging

from backend.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.unusualwhales.com"


class UnusualWhalesSource:
    def __init__(self):
        self.api_key = settings.uw_api_key

    def get_options_flow(self, ticker: str) -> dict:
        logger.info("Unusual Whales options flow not yet implemented for %s", ticker)
        return {}

    def get_dark_pool(self, ticker: str) -> dict:
        logger.info("Unusual Whales dark pool not yet implemented for %s", ticker)
        return {}

    def get_institutional_holdings(self, ticker: str) -> dict:
        logger.info("Unusual Whales institutional not yet implemented for %s", ticker)
        return {}

    def get_congress_trades(self) -> list[dict]:
        logger.info("Unusual Whales congress trades not yet implemented")
        return []


uw_source = UnusualWhalesSource()

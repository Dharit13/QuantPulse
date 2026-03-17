"""Finnhub data source stub.

Enable by setting FINNHUB_API_KEY in .env.
Provides: analyst revisions, news + sentiment, earnings surprises.
"""

import logging

from backend.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://finnhub.io/api/v1"


class FinnhubSource:
    def __init__(self):
        self.api_key = settings.finnhub_api_key

    def get_analyst_revisions(self, ticker: str) -> dict:
        logger.info("Finnhub analyst revisions not yet implemented for %s", ticker)
        return {}

    def get_news(self, ticker: str, days_back: int = 7) -> list[dict]:
        logger.info("Finnhub news not yet implemented for %s", ticker)
        return []

    def get_earnings_surprises(self, ticker: str) -> list[dict]:
        logger.info("Finnhub earnings surprises not yet implemented for %s", ticker)
        return []

    def get_recommendation_trends(self, ticker: str) -> list[dict]:
        logger.info("Finnhub recommendations not yet implemented for %s", ticker)
        return []


finnhub_source = FinnhubSource()

"""QuiverQuant data source stub.

Enable by setting ENABLE_QUIVER=true and QUIVER_API_KEY in .env.
Provides: congress trades, government contracts, lobbying data.
"""

import logging

from backend.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.quiverquant.com/beta"


class QuiverSource:
    def __init__(self):
        self.api_key = settings.quiver_api_key

    def get_congress_trades(self, ticker: str | None = None) -> list[dict]:
        logger.info("Quiver congress trades not yet implemented")
        return []

    def get_government_contracts(self, ticker: str) -> list[dict]:
        logger.info("Quiver gov contracts not yet implemented for %s", ticker)
        return []


quiver_source = QuiverSource()

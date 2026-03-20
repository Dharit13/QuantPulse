"""In-memory per-ticker sentiment cache with TTL.

Populated by refresh_news_sentiment (every 2h) and consumed by
CatalystEventStrategy._apply_sentiment_boost for low-latency lookups.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 2 * 60 * 60 + 300  # 2h + 5min grace


@dataclass
class CachedSentiment:
    ticker: str
    composite_score: float  # 0-100
    sentiment_label: str  # "bullish" / "bearish" / "neutral"
    avg_compound: float
    article_count: int
    model_used: str  # "finbert" / "vader" / "none"
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def is_expired(self) -> bool:
        age = (datetime.now(UTC) - self.updated_at).total_seconds()
        return age > _CACHE_TTL_SECONDS


class SentimentCache:
    """Thread-safe in-memory sentiment cache keyed by ticker."""

    def __init__(self) -> None:
        self._store: dict[str, CachedSentiment] = {}
        self._lock = threading.Lock()

    def get(self, ticker: str) -> CachedSentiment | None:
        with self._lock:
            entry = self._store.get(ticker.upper())
            if entry is None or entry.is_expired():
                return None
            return entry

    def put(self, entry: CachedSentiment) -> None:
        with self._lock:
            self._store[entry.ticker.upper()] = entry

    def put_batch(self, entries: list[CachedSentiment]) -> None:
        with self._lock:
            for entry in entries:
                self._store[entry.ticker.upper()] = entry

    def size(self) -> int:
        with self._lock:
            return len(self._store)

    def clear_expired(self) -> int:
        with self._lock:
            expired = [k for k, v in self._store.items() if v.is_expired()]
            for k in expired:
                del self._store[k]
            return len(expired)

    def all_tickers(self) -> list[str]:
        with self._lock:
            return [k for k, v in self._store.items() if not v.is_expired()]


sentiment_cache = SentimentCache()

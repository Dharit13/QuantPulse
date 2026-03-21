"""Market news endpoint — returns recent headlines from yfinance (free)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter

from backend.api.envelope import ok
from backend.data.cache import data_cache

router = APIRouter(prefix="/news", tags=["news"])
logger = logging.getLogger(__name__)

_CACHE_KEY = "news:market_headlines_v2"
_CACHE_TTL_HOURS = 0.25  # 15 min


def _parse_item(raw: dict, ticker: str) -> dict | None:
    """Extract a structured news item from a yfinance news entry."""
    content = raw.get("content", raw)
    title = content.get("title", "") or raw.get("title", "")
    if not title:
        return None

    provider = content.get("provider", {})
    pub_date = content.get("pubDate", "") or raw.get("providerPublishTime", "")
    url = content.get("canonicalUrl", {}).get("url", "") or raw.get("link", "")

    published_at = ""
    if isinstance(pub_date, str) and pub_date:
        published_at = pub_date
    elif isinstance(pub_date, (int, float)):
        published_at = datetime.fromtimestamp(pub_date, tz=UTC).isoformat()

    return {
        "title": title,
        "source": provider.get("displayName", "") if isinstance(provider, dict) else str(provider) if provider else "",
        "url": url,
        "published_at": published_at,
        "related_ticker": ticker if ticker != "^VIX" else "VIX",
    }


def _fetch_market_news_full() -> list[dict]:
    """Fetch structured news from yfinance, round-robin across tickers for diversity."""
    buckets: dict[str, list[dict]] = {}
    seen: set[str] = set()

    try:
        import yfinance as yf

        for ticker in ["SPY", "QQQ", "DIA", "IWM", "^VIX"]:
            bucket: list[dict] = []
            try:
                t = yf.Ticker(ticker)
                for raw in (t.news or [])[:10]:
                    item = _parse_item(raw, ticker)
                    if not item or item["title"] in seen:
                        continue
                    seen.add(item["title"])
                    bucket.append(item)
            except Exception:
                continue
            if bucket:
                buckets[ticker] = bucket
    except Exception as e:
        logger.warning("Failed to fetch market news: %s", e)

    items: list[dict] = []
    max_per_ticker = max((len(b) for b in buckets.values()), default=0)
    for i in range(max_per_ticker):
        for bucket in buckets.values():
            if i < len(bucket):
                items.append(bucket[i])
            if len(items) >= 20:
                break
        if len(items) >= 20:
            break

    return items


@router.get("/market")
async def get_market_news():
    cached = data_cache.get(_CACHE_KEY)
    if cached is not None:
        return ok({"items": cached}, cached=True)

    items = _fetch_market_news_full()
    if items:
        data_cache.set(_CACHE_KEY, items, ttl_hours=_CACHE_TTL_HOURS)

    return ok({"items": items})

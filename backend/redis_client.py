"""Redis client singleton — used for cache, task queue, and WebSocket pub/sub.

Falls back gracefully when REDIS_URL is not set.
"""

import logging

import redis

from backend.config import settings

logger = logging.getLogger(__name__)

_client: redis.Redis | None = None
_available: bool | None = None


def get_redis() -> redis.Redis | None:
    """Return the shared Redis client, or None if Redis is unavailable."""
    global _client, _available

    if _available is False:
        return None

    if _client is not None:
        return _client

    if not settings.redis_url:
        logger.info("REDIS_URL not set — running without Redis (in-memory fallback)")
        _available = False
        return None

    try:
        _client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
        _client.ping()
        _available = True
        logger.info("Redis connected: %s", settings.redis_url.split("@")[-1] if "@" in settings.redis_url else "local")
        return _client
    except Exception as e:
        logger.warning("Redis connection failed (falling back to in-memory): %s", e)
        _client = None
        _available = False
        return None


def redis_available() -> bool:
    """Check if Redis is available without creating a connection."""
    if _available is not None:
        return _available
    return get_redis() is not None

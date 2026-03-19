"""Token bucket rate limiter with per-source limits and exponential backoff.

Used by all API sources to respect rate limits. Each source registers its own
bucket (e.g., SteadyAPI: 15 req/s, FMP: 250/day, Finnhub: 60/min, FRED: 120/min).
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)


@dataclass
class _Bucket:
    """Internal token bucket state for a single source."""

    tokens_per_second: float
    max_tokens: float
    tokens: float = field(init=False)
    last_refill: float = field(init=False)

    def __post_init__(self) -> None:
        self.tokens = self.max_tokens
        self.last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self.tokens_per_second)
        self.last_refill = now

    def try_acquire(self) -> float:
        """Try to consume one token. Returns 0.0 if acquired, else seconds to wait."""
        self._refill()
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return 0.0
        deficit = 1.0 - self.tokens
        return deficit / self.tokens_per_second


class RateLimiter:
    """Thread-safe token bucket rate limiter supporting multiple named sources.

    Usage::

        limiter = RateLimiter()
        limiter.register("steadyapi", tokens_per_second=15, burst=15)

        # Blocking acquire (sync)
        limiter.acquire("steadyapi")
        resp = httpx.get(...)

        # Or use the retry helper for automatic backoff on 429
        resp = limiter.request_with_retry("steadyapi", client, "GET", url)
    """

    def __init__(self) -> None:
        self._buckets: dict[str, _Bucket] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._sync_locks: dict[str, object] = {}

    def register(
        self,
        source: str,
        tokens_per_second: float,
        burst: int | None = None,
    ) -> None:
        """Register a named source with its rate limit.

        Args:
            source: Identifier (e.g. "steadyapi", "fmp", "finnhub").
            tokens_per_second: Sustained request rate.
            burst: Max burst size. Defaults to ``int(tokens_per_second)``.
        """
        max_tokens = float(burst if burst is not None else max(1, int(tokens_per_second)))
        self._buckets[source] = _Bucket(
            tokens_per_second=tokens_per_second,
            max_tokens=max_tokens,
        )

    def acquire(self, source: str) -> None:
        """Block (sync) until a token is available for *source*."""
        bucket = self._buckets.get(source)
        if bucket is None:
            return
        while True:
            wait = bucket.try_acquire()
            if wait == 0.0:
                return
            time.sleep(wait)

    async def acquire_async(self, source: str) -> None:
        """Await until a token is available for *source*."""
        bucket = self._buckets.get(source)
        if bucket is None:
            return

        if source not in self._locks:
            self._locks[source] = asyncio.Lock()

        async with self._locks[source]:
            while True:
                wait = bucket.try_acquire()
                if wait == 0.0:
                    return
                await asyncio.sleep(wait)

    def request_with_retry(
        self,
        source: str,
        client: httpx.Client,
        method: str,
        url: str,
        *,
        max_retries: int = 3,
        base_backoff: float = 1.0,
        **kwargs,
    ) -> httpx.Response:
        """Make an HTTP request with rate limiting and exponential backoff on 429.

        Raises ``httpx.HTTPStatusError`` after exhausting retries for non-429 errors.
        """
        for attempt in range(max_retries + 1):
            self.acquire(source)
            try:
                resp = client.request(method, url, **kwargs)
                if resp.status_code == 429:
                    if attempt < max_retries:
                        retry_after = float(resp.headers.get("Retry-After", base_backoff * 2**attempt))
                        logger.warning(
                            "%s rate-limited (429), retry %d/%d in %.1fs",
                            source,
                            attempt + 1,
                            max_retries,
                            retry_after,
                        )
                        time.sleep(retry_after)
                        continue
                    logger.warning("%s rate-limited (429), all %d retries exhausted", source, max_retries)
                resp.raise_for_status()
                return resp
            except httpx.HTTPStatusError:
                if attempt < max_retries and resp.status_code == 429:
                    continue
                raise
            except httpx.RequestError as exc:
                if attempt < max_retries:
                    backoff = base_backoff * 2**attempt
                    logger.warning(
                        "%s request error (%s), retry %d/%d in %.1fs",
                        source,
                        exc,
                        attempt + 1,
                        max_retries,
                        backoff,
                    )
                    time.sleep(backoff)
                    continue
                raise

        raise httpx.HTTPStatusError(
            f"{source}: exhausted {max_retries} retries",
            request=httpx.Request(method, url),
            response=resp,
        )

    async def request_with_retry_async(
        self,
        source: str,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        max_retries: int = 3,
        base_backoff: float = 1.0,
        **kwargs,
    ) -> httpx.Response:
        """Async version of :meth:`request_with_retry`."""
        resp: httpx.Response | None = None
        for attempt in range(max_retries + 1):
            await self.acquire_async(source)
            try:
                resp = await client.request(method, url, **kwargs)
                if resp.status_code == 429:
                    if attempt < max_retries:
                        retry_after = float(resp.headers.get("Retry-After", base_backoff * 2**attempt))
                        logger.warning(
                            "%s rate-limited (429), retry %d/%d in %.1fs",
                            source,
                            attempt + 1,
                            max_retries,
                            retry_after,
                        )
                        await asyncio.sleep(retry_after)
                        continue
                    logger.warning("%s rate-limited (429), all %d retries exhausted", source, max_retries)
                resp.raise_for_status()
                return resp
            except httpx.HTTPStatusError:
                if resp is not None and attempt < max_retries and resp.status_code == 429:
                    continue
                raise
            except httpx.RequestError as exc:
                if attempt < max_retries:
                    backoff = base_backoff * 2**attempt
                    logger.warning(
                        "%s request error (%s), retry %d/%d in %.1fs",
                        source,
                        exc,
                        attempt + 1,
                        max_retries,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue
                raise

        assert resp is not None
        raise httpx.HTTPStatusError(
            f"{source}: exhausted {max_retries} retries",
            request=httpx.Request(method, url),
            response=resp,
        )


rate_limiter = RateLimiter()

# ── Pre-register known sources ──
rate_limiter.register("steadyapi", tokens_per_second=12, burst=15)  # 15/s limit, slight safety margin
rate_limiter.register("fmp", tokens_per_second=5, burst=10)           # Starter plan: 300/min → 5/s
rate_limiter.register("finnhub", tokens_per_second=1, burst=5)      # 60/min
rate_limiter.register("fred", tokens_per_second=2, burst=5)         # 120/min
rate_limiter.register("edgar", tokens_per_second=8, burst=10)       # 10/sec SEC policy
rate_limiter.register("polygon", tokens_per_second=5, burst=10)     # free: unlimited, paid: 100+/s
rate_limiter.register("unusual_whales", tokens_per_second=2, burst=5)  # ~120/min
rate_limiter.register("finra", tokens_per_second=2, burst=5)        # public data, be polite

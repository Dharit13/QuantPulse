"""Three-tier cache: Redis (primary) → in-memory (fallback) → Supabase (persistence).

When Redis is available (REDIS_URL set), it is the primary store with native TTL.
When Redis is unavailable, falls back to the in-memory dict (original behavior).
Supabase is the durable backup for critical pipeline keys.
"""

import json
import logging
import threading
import time
from datetime import UTC, datetime, timedelta

import pandas as pd

from backend.models.database import get_supabase, reset_client

logger = logging.getLogger(__name__)

MAX_RETRIES = 2
RETRY_DELAY = 0.5

_mem: dict[str, tuple[datetime, object]] = {}
_mem_lock = threading.Lock()

_CRITICAL_PREFIXES = ("pipeline:", "regime:", "ai:")


def _with_retry(fn):
    """Retry Supabase operations on connection errors."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            return fn()
        except Exception as e:
            err_msg = str(e).lower()
            is_connection_err = any(
                k in err_msg
                for k in ["disconnected", "connection", "reset", "broken pipe", "timeout"]
            )
            if is_connection_err and attempt < MAX_RETRIES:
                reset_client()
                time.sleep(RETRY_DELAY * (attempt + 1))
                logger.debug("Supabase retry %d after: %s", attempt + 1, e)
                continue
            raise


def _serialize(value: dict | pd.DataFrame) -> str:
    if isinstance(value, pd.DataFrame):
        df_reset = value.reset_index(drop=False)
        return json.dumps({"__type__": "dataframe", "data": df_reset.to_dict()}, default=str)
    return json.dumps(value, default=str)


def _deserialize(raw: str) -> dict | pd.DataFrame:
    data = json.loads(raw)
    if isinstance(data, dict) and data.get("__type__") == "dataframe":
        return pd.DataFrame.from_dict(data["data"])
    return data


class DataCache:
    """Three-tier cache with Redis primary, in-memory fallback, Supabase persistence."""

    def __init__(self) -> None:
        self._redis = None
        self._redis_checked = False

    def _get_redis(self):
        if not self._redis_checked:
            from backend.redis_client import get_redis
            self._redis = get_redis()
            self._redis_checked = True
        return self._redis

    def get(self, key: str) -> dict | pd.DataFrame | None:
        r = self._get_redis()
        if r is not None:
            try:
                raw = r.get(f"cache:{key}")
                if raw is not None:
                    return _deserialize(raw)
            except Exception:
                logger.debug("Redis GET failed for %s, trying memory", key)

        with _mem_lock:
            entry = _mem.get(key)
            if entry:
                expires, value = entry
                if datetime.now(UTC) < expires:
                    return value
                del _mem[key]

        try:
            result = _with_retry(lambda: get_supabase().table("data_cache").select("*").eq("cache_key", key).execute())
        except Exception:
            logger.debug("Cache get failed for key %s", key)
            return None

        if not result.data:
            return None

        record = result.data[0]
        expires_at = datetime.fromisoformat(record["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)

        if datetime.now(UTC) > expires_at:
            try:
                _with_retry(lambda: get_supabase().table("data_cache").delete().eq("cache_key", key).execute())
            except Exception:
                pass
            return None

        value = _deserialize(record["data_json"])

        with _mem_lock:
            _mem[key] = (expires_at, value)

        if r is not None:
            ttl_sec = max(1, int((expires_at - datetime.now(UTC)).total_seconds()))
            try:
                r.setex(f"cache:{key}", ttl_sec, record["data_json"])
            except Exception:
                pass

        return value

    def set(self, key: str, value: dict | pd.DataFrame, ttl_hours: float = 1.0) -> None:
        now = datetime.now(UTC)
        expires = now + timedelta(hours=ttl_hours)
        ttl_sec = max(1, int(ttl_hours * 3600))
        serialized = _serialize(value)

        r = self._get_redis()
        if r is not None:
            try:
                r.setex(f"cache:{key}", ttl_sec, serialized)
            except Exception:
                logger.debug("Redis SET failed for %s", key)

        with _mem_lock:
            _mem[key] = (expires, value)

        is_critical = any(key.startswith(p) for p in _CRITICAL_PREFIXES)
        if is_critical:
            row = {
                "cache_key": key,
                "data_json": serialized,
                "created_at": now.isoformat(),
                "expires_at": expires.isoformat(),
            }

            def _write() -> None:
                try:
                    _with_retry(
                        lambda: get_supabase().table("data_cache").upsert(row, on_conflict="cache_key").execute()
                    )
                except Exception:
                    logger.warning("Cache write failed for key %s", key)

            threading.Thread(target=_write, daemon=True).start()

    def invalidate(self, key: str) -> None:
        r = self._get_redis()
        if r is not None:
            try:
                r.delete(f"cache:{key}")
            except Exception:
                pass

        with _mem_lock:
            _mem.pop(key, None)

        try:
            _with_retry(lambda: get_supabase().table("data_cache").delete().eq("cache_key", key).execute())
        except Exception:
            logger.debug("Cache invalidate failed for key %s", key)

    def clear_expired(self) -> int:
        with _mem_lock:
            now = datetime.now(UTC)
            expired_keys = [k for k, (exp, _) in _mem.items() if now >= exp]
            for k in expired_keys:
                del _mem[k]

        now_iso = now.isoformat()
        try:
            result = _with_retry(
                lambda: get_supabase().table("data_cache").select("id").lt("expires_at", now_iso).limit(200).execute()
            )
            ids = [r["id"] for r in result.data] if result.data else []
            if ids:
                for i in range(0, len(ids), 50):
                    batch = ids[i : i + 50]
                    _with_retry(
                        lambda b=batch: get_supabase().table("data_cache").delete().in_("id", b).execute()
                    )
                logger.info("Cleared %d expired cache entries", len(ids))
            return len(ids)
        except Exception as e:
            logger.debug("Cache cleanup skipped (Supabase timeout): %s", type(e).__name__)
            return 0


data_cache = DataCache()

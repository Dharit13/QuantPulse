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


def _with_retry(fn):
    """Retry Supabase operations on connection errors."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            return fn()
        except Exception as e:
            err_msg = str(e).lower()
            is_connection_err = any(
                k in err_msg
                for k in [
                    "disconnected",
                    "connection",
                    "reset",
                    "broken pipe",
                    "timeout",
                ]
            )
            if is_connection_err and attempt < MAX_RETRIES:
                reset_client()
                time.sleep(RETRY_DELAY * (attempt + 1))
                logger.debug("Supabase retry %d after: %s", attempt + 1, e)
                continue
            raise


class DataCache:
    """Supabase-backed cache with TTL-based invalidation and retry logic."""

    def get(self, key: str) -> dict | pd.DataFrame | None:
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

        data = json.loads(record["data_json"])
        if isinstance(data, dict) and data.get("__type__") == "dataframe":
            return pd.DataFrame.from_dict(data["data"])
        return data

    def set(self, key: str, value: dict | pd.DataFrame, ttl_hours: float = 1.0) -> None:
        now = datetime.now(UTC)
        expires = now + timedelta(hours=ttl_hours)

        if isinstance(value, pd.DataFrame):
            df_reset = value.reset_index(drop=False)
            serialized = json.dumps({"__type__": "dataframe", "data": df_reset.to_dict()}, default=str)
        else:
            serialized = json.dumps(value, default=str)

        row = {
            "cache_key": key,
            "data_json": serialized,
            "created_at": now.isoformat(),
            "expires_at": expires.isoformat(),
        }

        def _write() -> None:
            try:
                _with_retry(lambda: get_supabase().table("data_cache").upsert(row, on_conflict="cache_key").execute())
            except Exception:
                logger.warning("Cache write failed for key %s", key)

        threading.Thread(target=_write, daemon=True).start()

    def invalidate(self, key: str) -> None:
        try:
            _with_retry(lambda: get_supabase().table("data_cache").delete().eq("cache_key", key).execute())
        except Exception:
            logger.debug("Cache invalidate failed for key %s", key)

    def clear_expired(self) -> int:
        now = datetime.now(UTC).isoformat()
        try:
            result = _with_retry(
                lambda: get_supabase().table("data_cache").select("id").lt("expires_at", now).execute()
            )
            count = len(result.data) if result.data else 0
            if count:
                _with_retry(lambda: get_supabase().table("data_cache").delete().lt("expires_at", now).execute())
                logger.info("Cleared %d expired cache entries", count)
            return count
        except Exception:
            logger.exception("Failed to clear expired cache entries")
            return 0


data_cache = DataCache()

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
    """Two-tier cache: fast in-memory dict + Supabase persistence.

    Reads check memory first (instant), then Supabase.
    Writes always update both memory and Supabase (async).
    """

    def get(self, key: str) -> dict | pd.DataFrame | None:
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

        data = json.loads(record["data_json"])
        if isinstance(data, dict) and data.get("__type__") == "dataframe":
            value = pd.DataFrame.from_dict(data["data"])
        else:
            value = data

        with _mem_lock:
            _mem[key] = (expires_at, value)
        return value

    def set(self, key: str, value: dict | pd.DataFrame, ttl_hours: float = 1.0) -> None:
        now = datetime.now(UTC)
        expires = now + timedelta(hours=ttl_hours)

        with _mem_lock:
            _mem[key] = (expires, value)

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

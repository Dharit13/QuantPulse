import json
import logging
from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import delete, text

from backend.models.database import CacheRecord, SessionLocal

logger = logging.getLogger(__name__)


class DataCache:
    """SQLite/PostgreSQL cache with TTL-based invalidation."""

    def get(self, key: str) -> dict | pd.DataFrame | None:
        with SessionLocal() as session:
            record = session.query(CacheRecord).filter_by(cache_key=key).first()
            if record is None:
                return None
            if datetime.utcnow() > record.expires_at:
                try:
                    session.execute(
                        delete(CacheRecord).where(CacheRecord.cache_key == key)
                    )
                    session.commit()
                except Exception:
                    session.rollback()
                return None
            data = json.loads(record.data_json)
            if isinstance(data, dict) and data.get("__type__") == "dataframe":
                return pd.DataFrame.from_dict(data["data"])
            return data

    def set(self, key: str, value: dict | pd.DataFrame, ttl_hours: float = 1.0) -> None:
        expires = datetime.utcnow() + timedelta(hours=ttl_hours)

        if isinstance(value, pd.DataFrame):
            df_reset = value.reset_index(drop=False)
            serialized = json.dumps({"__type__": "dataframe", "data": df_reset.to_dict()}, default=str)
        else:
            serialized = json.dumps(value, default=str)

        with SessionLocal() as session:
            try:
                session.execute(
                    text(
                        "INSERT INTO data_cache (cache_key, data_json, created_at, expires_at) "
                        "VALUES (:key, :data, :created, :expires) "
                        "ON CONFLICT(cache_key) DO UPDATE SET "
                        "data_json = excluded.data_json, "
                        "created_at = excluded.created_at, "
                        "expires_at = excluded.expires_at"
                    ),
                    {
                        "key": key,
                        "data": serialized,
                        "created": datetime.utcnow(),
                        "expires": expires,
                    },
                )
                session.commit()
            except Exception:
                session.rollback()
                logger.exception("Cache set failed for key %s", key)

    def invalidate(self, key: str) -> None:
        with SessionLocal() as session:
            session.execute(delete(CacheRecord).where(CacheRecord.cache_key == key))
            session.commit()

    def clear_expired(self) -> int:
        with SessionLocal() as session:
            result = session.execute(
                delete(CacheRecord).where(CacheRecord.expires_at < datetime.utcnow())
            )
            session.commit()
            count = result.rowcount
            if count:
                logger.info("Cleared %d expired cache entries", count)
            return count


data_cache = DataCache()

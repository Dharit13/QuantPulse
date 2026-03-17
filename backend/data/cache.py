import json
import logging
from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import delete

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
                session.delete(record)
                session.commit()
                return None
            data = json.loads(record.data_json)
            if isinstance(data, dict) and data.get("__type__") == "dataframe":
                return pd.DataFrame.from_dict(data["data"])
            return data

    def set(self, key: str, value: dict | pd.DataFrame, ttl_hours: float = 1.0) -> None:
        expires = datetime.utcnow() + timedelta(hours=ttl_hours)

        if isinstance(value, pd.DataFrame):
            serialized = json.dumps({"__type__": "dataframe", "data": value.to_dict()})
        else:
            serialized = json.dumps(value, default=str)

        with SessionLocal() as session:
            existing = session.query(CacheRecord).filter_by(cache_key=key).first()
            if existing:
                existing.data_json = serialized
                existing.expires_at = expires
                existing.created_at = datetime.utcnow()
            else:
                session.add(CacheRecord(
                    cache_key=key,
                    data_json=serialized,
                    expires_at=expires,
                ))
            session.commit()

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

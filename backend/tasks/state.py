"""Redis-backed task state for cross-process SSE polling.

Each task type (scanner, analyzer, portfolio, etc.) gets a Redis hash
that stores its current status, progress, step, result, and error.
Falls back to in-memory dict when Redis is unavailable.
"""

import json
import logging
import threading
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

_mem_states: dict[str, dict] = {}
_mem_lock = threading.Lock()

_HASH_PREFIX = "taskstate:"
_RESULT_PREFIX = "taskresult:"
_TTL = 3600


class TaskState:
    """Manage background task state in Redis (with in-memory fallback)."""

    def __init__(self, namespace: str) -> None:
        self.namespace = namespace
        self._redis = None
        self._checked = False

    def _get_redis(self):
        if not self._checked:
            from backend.redis_client import get_redis

            self._redis = get_redis()
            self._checked = True
        return self._redis

    def update(self, **fields) -> None:
        """Update task state fields (status, progress, step, etc.)."""
        r = self._get_redis()
        if r is not None:
            try:
                key = f"{_HASH_PREFIX}{self.namespace}"
                serialized = {k: json.dumps(v, default=str) if not isinstance(v, str) else v for k, v in fields.items()}
                r.hset(key, mapping=serialized)
                r.expire(key, _TTL)
                return
            except Exception:
                logger.debug("TaskState Redis update failed for %s", self.namespace)

        with _mem_lock:
            if self.namespace not in _mem_states:
                _mem_states[self.namespace] = {}
            _mem_states[self.namespace].update(fields)

    def get(self) -> dict:
        """Get all task state fields."""
        r = self._get_redis()
        if r is not None:
            try:
                key = f"{_HASH_PREFIX}{self.namespace}"
                raw = r.hgetall(key)
                if raw:
                    result = {}
                    for k, v in raw.items():
                        try:
                            result[k] = json.loads(v)
                        except (json.JSONDecodeError, TypeError):
                            result[k] = v
                    return result
            except Exception:
                logger.debug("TaskState Redis get failed for %s", self.namespace)

        with _mem_lock:
            return dict(_mem_states.get(self.namespace, {}))

    def set_result(self, result: dict | list, ai_summary: dict | None = None, **extra) -> None:
        """Store final result and mark task as done."""
        r = self._get_redis()
        ts = datetime.now(UTC).isoformat()

        if r is not None:
            try:
                result_key = f"{_RESULT_PREFIX}{self.namespace}"
                r.setex(result_key, _TTL, json.dumps(result, default=str))

                fields: dict = {
                    "status": "done",
                    "result_timestamp": ts,
                    **extra,
                }
                if ai_summary is not None:
                    fields["ai_summary"] = json.dumps(ai_summary, default=str)

                state_key = f"{_HASH_PREFIX}{self.namespace}"
                serialized = {k: json.dumps(v, default=str) if not isinstance(v, str) else v for k, v in fields.items()}
                r.hset(state_key, mapping=serialized)
                r.expire(state_key, _TTL)
                return
            except Exception:
                logger.debug("TaskState Redis set_result failed for %s", self.namespace)

        with _mem_lock:
            if self.namespace not in _mem_states:
                _mem_states[self.namespace] = {}
            _mem_states[self.namespace]["status"] = "done"
            _mem_states[self.namespace]["result"] = result
            _mem_states[self.namespace]["result_timestamp"] = ts
            if ai_summary is not None:
                _mem_states[self.namespace]["ai_summary"] = ai_summary
            _mem_states[self.namespace].update(extra)

    def get_result(self) -> dict | list | None:
        """Retrieve the stored result (separate from state for size reasons)."""
        r = self._get_redis()
        if r is not None:
            try:
                raw = r.get(f"{_RESULT_PREFIX}{self.namespace}")
                if raw:
                    return json.loads(raw)
            except Exception:
                pass

        with _mem_lock:
            return _mem_states.get(self.namespace, {}).get("result")

    def reset(self, **initial) -> None:
        """Reset state for a new task run."""
        defaults = {
            "status": "idle",
            "progress": 0,
            "total": 0,
            "step": "",
            "error": None,
        }
        defaults.update(initial)
        self.update(**defaults)

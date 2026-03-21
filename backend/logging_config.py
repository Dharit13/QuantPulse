"""Structured JSON logging for Railway native log search.

Outputs one JSON object per log line so Railway's log viewer can filter
by level, logger, request_id, strategy, duration_ms, etc.
"""

import json
import logging
import sys
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="")


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = request_id_var.get("")
        if rid:
            entry["request_id"] = rid
        for attr in ("strategy", "duration_ms", "ticker", "status_code", "method", "path"):
            val = getattr(record, attr, None)
            if val is not None:
                entry[attr] = val
        if record.exc_info and record.exc_info[1]:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    for noisy in ("httpx", "httpcore", "urllib3", "hpack", "apscheduler.executors"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

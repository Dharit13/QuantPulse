"""Backtest seeder API — seed phantom_trades with historically resolved
signals so win rate and strategy health metrics work from day one."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from fastapi import APIRouter

from backend.api.envelope import ok

router = APIRouter(prefix="/backtest", tags=["backtest"])
logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=1)

_seed_state: dict = {
    "status": "idle",
    "progress": 0,
    "total": 0,
    "step": "",
    "result": None,
    "error": None,
    "started_at": None,
}
_seed_lock = threading.Lock()


def _run_seed_background() -> None:
    global _seed_state
    try:
        _seed_state["status"] = "scanning"
        _seed_state["started_at"] = datetime.now(UTC).isoformat()
        _seed_state["error"] = None
        _seed_state["result"] = None

        def _on_progress(done: int, total: int, step: str) -> None:
            _seed_state["progress"] = done
            _seed_state["total"] = total
            _seed_state["step"] = step

        from backend.backtest.seeder import run_backtest_seed

        result = run_backtest_seed(progress_cb=_on_progress)

        _seed_state["result"] = result
        _seed_state["status"] = "done"
        logger.info("Backtest seed complete: %s", result)
    except Exception as e:
        _seed_state["status"] = "error"
        _seed_state["error"] = str(e)
        logger.exception("Backtest seed failed")


@router.post("/seed")
async def start_seed() -> dict:
    """Kick off a backtest seed run in the background."""
    with _seed_lock:
        if _seed_state["status"] == "scanning":
            return ok(
                {
                    "status": "already_running",
                    "progress": _seed_state["progress"],
                    "total": _seed_state["total"],
                }
            )

        _seed_state["status"] = "scanning"
        _seed_state["progress"] = 0
        _seed_state["total"] = 0
        _seed_state["step"] = "Starting..."
        _seed_state["result"] = None
        _seed_state["error"] = None

    _executor.submit(_run_seed_background)
    return ok({"status": "started"})


@router.get("/status")
async def get_seed_status() -> dict:
    """Poll backtest seed progress."""
    return ok(
        {
            "status": _seed_state["status"],
            "progress": _seed_state["progress"],
            "total": _seed_state["total"],
            "step": _seed_state.get("step", ""),
            "result": _seed_state["result"],
            "started_at": _seed_state.get("started_at"),
            "error": _seed_state["error"],
        }
    )

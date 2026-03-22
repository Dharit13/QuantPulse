"""ARQ worker — processes background tasks from the Redis queue.

Each task function mirrors the background work from the API modules
but routes state updates through TaskState for cross-process visibility.
"""

import logging
from typing import Any

from backend.tasks.state import TaskState

logger = logging.getLogger(__name__)


async def task_run_scan(ctx: dict | None, max_signals: int = 10, min_score: float = 60.0, **kwargs: Any) -> dict:
    """Run a full scanner scan as a background task."""
    state = TaskState("scanner")
    state.update(status="scanning", progress=0, total=0, error=None)

    try:
        from backend.api.scanner import _run_scanner_background

        _run_scanner_background(max_signals, min_score)
        return {"status": "complete"}
    except Exception as e:
        state.update(status="error", error=str(e))
        logger.error("Task scan failed: %s", e)
        raise


async def task_run_analysis(ctx: dict | None, ticker: str = "", capital: float = 10000, **kwargs: Any) -> dict:
    """Run single-stock analysis as a background task."""
    state = TaskState("analysis")
    state.update(status="scanning", ticker=ticker, progress=0, error=None)

    try:
        from backend.api.analyzer import _run_analysis_background

        _run_analysis_background(ticker, capital)
        return {"status": "complete", "ticker": ticker}
    except Exception as e:
        state.update(status="error", error=str(e))
        logger.error("Task analysis failed for %s: %s", ticker, e)
        raise


async def task_run_portfolio(ctx: dict | None, capital: float = 10000, **kwargs: Any) -> dict:
    """Run portfolio allocation as a background task."""
    state = TaskState("portfolio")
    state.update(status="scanning", progress=0, error=None)

    try:
        from backend.api.portfolio import _run_portfolio_background

        _run_portfolio_background(capital)
        return {"status": "complete"}
    except Exception as e:
        state.update(status="error", error=str(e))
        logger.error("Task portfolio failed: %s", e)
        raise


async def task_run_sectors(ctx: dict | None, refresh: bool = False, **kwargs: Any) -> dict:
    """Run sector recommendations as a background task."""
    try:
        from backend.api.sectors import _run_recs_background

        _run_recs_background(refresh)
        return {"status": "complete"}
    except Exception as e:
        logger.error("Task sectors failed: %s", e)
        raise


async def task_run_swing(
    ctx: dict | None, min_return_pct: float = 30.0, max_hold_days: int = 10, **kwargs: Any
) -> dict:
    """Run swing picks scan as a background task."""
    try:
        from backend.api.swing_picks import _run_scan_background

        _run_scan_background(min_return_pct, max_hold_days)
        return {"status": "complete"}
    except Exception as e:
        logger.error("Task swing failed: %s", e)
        raise


TASK_FUNCTIONS = {
    "task_run_scan": task_run_scan,
    "task_run_analysis": task_run_analysis,
    "task_run_portfolio": task_run_portfolio,
    "task_run_sectors": task_run_sectors,
    "task_run_swing": task_run_swing,
}


class WorkerSettings:
    """ARQ worker settings."""

    functions = list(TASK_FUNCTIONS.values())
    max_jobs = 4
    job_timeout = 600
    max_tries = 3
    health_check_interval = 30

    @staticmethod
    def redis_settings():
        from arq.connections import RedisSettings

        from backend.config import settings

        url = settings.redis_url
        if not url:
            return RedisSettings()

        if "@" in url:
            auth_host = url.split("@")
            password_part = auth_host[0].split(":")[-1]
            host_port = auth_host[1]
            host = host_port.split(":")[0]
            port = int(host_port.split(":")[1]) if ":" in host_port else 6379
        else:
            stripped = url.replace("redis://", "")
            host = stripped.split(":")[0]
            port = int(stripped.split(":")[1]) if ":" in stripped else 6379
            password_part = None

        return RedisSettings(host=host, port=port, password=password_part)


if __name__ == "__main__":
    import arq

    from backend.logging_config import setup_logging

    setup_logging()
    arq.run_worker(WorkerSettings)

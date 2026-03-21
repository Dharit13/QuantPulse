"""ARQ worker — processes background tasks from the Redis queue.

Run as: uv run python -m backend.tasks.worker
Or via the worker.py entry point.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def task_run_scan(ctx: dict | None, scan_type: str = "scanner", **kwargs: Any) -> dict:
    """Run a scanner/swing scan as a background task."""
    from backend.pipeline import refresh_medium

    logger.info("Task: running scan (%s)", scan_type)
    try:
        refresh_medium()
        return {"status": "complete", "scan_type": scan_type}
    except Exception as e:
        logger.error("Task scan failed: %s", e)
        raise


async def task_run_analysis(ctx: dict | None, ticker: str = "", capital: float = 10000, **kwargs: Any) -> dict:
    """Run single-stock analysis as a background task."""
    logger.info("Task: analyzing %s", ticker)
    try:
        from backend.api.analyzer import _run_analysis_sync

        result = _run_analysis_sync(ticker, capital)
        return {"status": "complete", "ticker": ticker, "result": result}
    except Exception as e:
        logger.error("Task analysis failed for %s: %s", ticker, e)
        raise


async def task_run_portfolio(ctx: dict | None, capital: float = 10000, **kwargs: Any) -> dict:
    """Run portfolio allocation as a background task."""
    logger.info("Task: portfolio allocation ($%.0f)", capital)
    try:
        from backend.api.portfolio import _run_allocate_sync

        result = _run_allocate_sync(capital)
        return {"status": "complete", "result": result}
    except Exception as e:
        logger.error("Task portfolio failed: %s", e)
        raise


async def task_ai_summarize(ctx: dict | None, data: dict | None = None, **kwargs: Any) -> dict:
    """Run AI summarization as a background task."""
    logger.info("Task: AI summarize")
    try:
        from backend.ai.market_ai import ai_market_summary

        result = ai_market_summary(data or {})
        return {"status": "complete", "result": result}
    except Exception as e:
        logger.error("Task AI summarize failed: %s", e)
        raise


TASK_FUNCTIONS = {
    "task_run_scan": task_run_scan,
    "task_run_analysis": task_run_analysis,
    "task_run_portfolio": task_run_portfolio,
    "task_ai_summarize": task_ai_summarize,
}


class WorkerSettings:
    """ARQ worker settings — discovers tasks and connects to Redis."""

    functions = list(TASK_FUNCTIONS.values())
    max_jobs = 4
    job_timeout = 300
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

    on_startup = None
    on_shutdown = None


if __name__ == "__main__":
    import arq

    from backend.logging_config import setup_logging

    setup_logging()
    arq.run_worker(WorkerSettings)

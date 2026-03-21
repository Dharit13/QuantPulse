"""Task queue helpers — enqueue background work via ARQ (Redis) or ThreadPoolExecutor fallback.

When Redis is available, tasks are enqueued to ARQ with retry, timeout, and persistence.
When Redis is unavailable, falls back to the original ThreadPoolExecutor approach.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4)

_ARQ_POOL = None


async def _get_arq_pool():
    global _ARQ_POOL
    if _ARQ_POOL is not None:
        return _ARQ_POOL

    from backend.redis_client import redis_available

    if not redis_available():
        return None

    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        from backend.config import settings

        if not settings.redis_url:
            return None

        url = settings.redis_url
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

        redis_settings = RedisSettings(host=host, port=port, password=password_part)
        _ARQ_POOL = await create_pool(redis_settings)
        logger.info("ARQ pool created")
        return _ARQ_POOL
    except Exception as e:
        logger.warning("ARQ pool creation failed (using ThreadPoolExecutor): %s", e)
        return None


async def enqueue(
    task_name: str,
    *args: Any,
    _timeout: int = 300,
    **kwargs: Any,
) -> str | None:
    """Enqueue a task to ARQ or run in ThreadPoolExecutor fallback.

    Returns a job ID (ARQ) or None (fallback).
    """
    pool = await _get_arq_pool()

    if pool is not None:
        try:
            job = await pool.enqueue_job(task_name, *args, _job_timeout=_timeout, **kwargs)
            if job:
                logger.info("Task enqueued to ARQ: %s (job=%s)", task_name, job.job_id)
                return job.job_id
        except Exception as e:
            logger.warning("ARQ enqueue failed for %s, falling back to executor: %s", task_name, e)

    loop = asyncio.get_event_loop()
    from backend.tasks.worker import TASK_FUNCTIONS

    func = TASK_FUNCTIONS.get(task_name)
    if func is None:
        logger.error("Unknown task: %s", task_name)
        return None

    logger.info("Task running in ThreadPoolExecutor: %s", task_name)
    loop.run_in_executor(_executor, lambda: func(None, *args, **kwargs))
    return None


async def get_task_status(job_id: str) -> dict | None:
    """Check ARQ job status."""
    pool = await _get_arq_pool()
    if pool is None or job_id is None:
        return None

    try:
        from arq.jobs import Job

        job = Job(job_id, pool)
        info = await job.info()
        if info is None:
            return None
        return {
            "job_id": job_id,
            "status": info.status,
            "result": info.result if info.status == "complete" else None,
        }
    except Exception:
        return None

"""QuantPulse Worker — runs APScheduler jobs and ARQ task queue.

Deployed as a separate Railway service from the API.
Does not serve HTTP traffic.
"""

import logging
import signal
import threading

from backend.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("Worker starting...")

    from apscheduler.schedulers.background import BackgroundScheduler

    from backend.scheduler import register_all_jobs

    scheduler = BackgroundScheduler()
    register_all_jobs(scheduler)
    scheduler.start()
    logger.info("APScheduler started with %d jobs", len(scheduler.get_jobs()))

    arq_thread = None
    try:
        from backend.redis_client import redis_available

        if redis_available():
            def _run_arq():
                import arq

                from backend.tasks.worker import WorkerSettings

                logger.info("ARQ worker starting...")
                arq.run_worker(WorkerSettings)

            arq_thread = threading.Thread(target=_run_arq, daemon=True)
            arq_thread.start()
            logger.info("ARQ worker started in background thread")
        else:
            logger.info("Redis unavailable — ARQ worker not started (tasks will run in API process)")
    except Exception as e:
        logger.warning("ARQ worker start failed (non-fatal): %s", e)

    # Warmup: populate cache and data tables
    def _warmup():
        logger.info("Worker warmup: refreshing regime...")
        try:
            from backend.pipeline import refresh_regime

            result = refresh_regime()
            if result:
                logger.info("Worker warmup: regime cache ready")
        except Exception as e:
            logger.warning("Worker warmup: regime refresh failed: %s", e)

        logger.info("Worker warmup: initial data load...")
        try:
            from backend.data.refresh_scheduler import initial_data_load

            initial_data_load()
            logger.info("Worker warmup: data tables populated")
        except Exception as e:
            logger.warning("Worker warmup: initial data load failed: %s", e)

        try:
            from backend.pipeline import refresh_all

            refresh_all()
            logger.info("Worker warmup: pipeline cache warm")
        except Exception as e:
            logger.warning("Worker warmup: pipeline warmup failed: %s", e)

    threading.Thread(target=_warmup, daemon=True).start()

    shutdown = threading.Event()

    def _signal_handler(signum, frame):
        logger.info("Worker received signal %d, shutting down...", signum)
        shutdown.set()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    try:
        shutdown.wait()
    except KeyboardInterrupt:
        pass
    finally:
        scheduler.shutdown(wait=False)
        logger.info("Worker shut down cleanly")


if __name__ == "__main__":
    main()

"""QuantPulse v2 — FastAPI application.

Mounts the API router, initializes the Supabase client, and configures
the APScheduler for all recurring calibration and monitoring jobs.
"""

from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.router import api_router
from backend.scheduler import register_all_jobs

scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from backend.data.cache import data_cache

    cleared = data_cache.clear_expired()
    if cleared:
        import logging

        logging.getLogger(__name__).info("Startup: cleared %d expired cache entries", cleared)
    register_all_jobs(scheduler)
    scheduler.start()

    import threading

    def _warmup():
        import logging

        log = logging.getLogger(__name__)
        log.info("Startup: populating data tables + warming pipeline cache...")
        try:
            from backend.data.refresh_scheduler import initial_data_load

            initial_data_load()
            log.info("Startup: data tables populated")
        except Exception as e:
            log.warning("Startup: initial data load failed: %s", e)
        try:
            from backend.pipeline import refresh_all

            refresh_all()
            log.info("Startup: pipeline cache warm")
        except Exception as e:
            log.warning("Startup: pipeline warmup failed: %s", e)

    threading.Thread(target=_warmup, daemon=True).start()

    yield
    scheduler.shutdown(wait=False)


app = FastAPI(
    title="QuantPulse v2",
    description="Institutional-grade multi-strategy quantitative trading advisory system",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}

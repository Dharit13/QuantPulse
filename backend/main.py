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
    import logging
    log = logging.getLogger(__name__)

    def _startup_tasks():
        try:
            from backend.data.cache import data_cache
            cleared = data_cache.clear_expired()
            if cleared:
                log.info("Startup: cleared %d expired cache entries", cleared)
        except Exception as e:
            log.warning("Startup: cache clear failed (non-fatal): %s", e)

    try:
        register_all_jobs(scheduler)
        scheduler.start()
    except Exception as e:
        log.warning("Startup: scheduler failed (non-fatal): %s", e)

    import threading
    threading.Thread(target=_startup_tasks, daemon=True).start()

    import threading

    def _warmup():
        import logging

        log = logging.getLogger(__name__)

        log.info("Startup: warming regime cache (priority)...")
        try:
            from backend.pipeline import refresh_regime

            result = refresh_regime()
            if result:
                log.info("Startup: regime cache ready")
                _prewarm_dashboard_ai(result, log)
        except Exception as e:
            log.warning("Startup: regime warmup failed: %s", e)

        log.info("Startup: populating data tables...")
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

    def _prewarm_dashboard_ai(regime_data: dict, log):
        """Pre-compute the 4 dashboard AI summaries so the frontend loads instantly."""
        try:
            from backend.ai.market_ai import (
                ai_allocation_explain,
                ai_market_action_banner,
                ai_market_summary,
                ai_regime_probs,
            )
            from backend.data.cache import data_cache

            import hashlib, json

            def _cache_key(req_type: str, data: dict) -> str:
                fp = {"regime": data.get("regime", ""), "vix": round(data.get("vix", 0), 0), "confidence": round(data.get("confidence", 0), 1)}
                h = hashlib.md5(json.dumps(fp, sort_keys=True).encode()).hexdigest()[:8]
                return f"ai:{req_type}:{h}"

            ai_types = [
                ("market", ai_market_summary),
                ("regime_probs", lambda d: ai_regime_probs({"probabilities": d.get("regime_probabilities"), "vix": d.get("vix"), "adx": d.get("adx"), "breadth_pct": d.get("breadth_pct")})),
                ("allocation_explain", ai_allocation_explain),
                ("market_action", ai_market_action_banner),
            ]

            for type_name, fn in ai_types:
                key = _cache_key(type_name, regime_data)
                if data_cache.get(key) is not None:
                    continue
                try:
                    result = fn(regime_data)
                    if result:
                        data_cache.set(key, result, ttl_hours=0.5)
                        log.info("Startup: pre-warmed AI %s", type_name)
                except Exception as e:
                    log.debug("Startup: AI pre-warm %s failed: %s", type_name, e)
        except Exception as e:
            log.debug("Startup: AI pre-warm skipped: %s", e)

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

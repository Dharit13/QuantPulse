"""QuantPulse v2 — FastAPI application.

Mounts the API router, initializes middleware stack (auth, rate limiting,
error tracking, request logging), and configures the APScheduler for all
recurring calibration and monitoring jobs.
"""

from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from backend.api.router import api_router
from backend.config import settings
from backend.logging_config import setup_logging
from backend.middleware.auth import AuthMiddleware
from backend.middleware.error_tracking import ErrorTrackingMiddleware
from backend.middleware.request_logging import RequestLoggingMiddleware
from backend.scheduler import register_all_jobs
from backend.websocket.routes import router as ws_router

setup_logging()

scheduler = BackgroundScheduler()
limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit_default])


@asynccontextmanager
async def lifespan(app: FastAPI):
    import logging
    import threading

    log = logging.getLogger(__name__)

    from backend.websocket.manager import manager
    await manager.start_redis_listener()

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

    threading.Thread(target=_startup_tasks, daemon=True).start()

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
            import hashlib
            import json

            from backend.ai.market_ai import (
                ai_allocation_explain,
                ai_market_action_banner,
                ai_market_summary,
                ai_regime_probs,
            )
            from backend.data.cache import data_cache

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

    await manager.shutdown()
    scheduler.shutdown(wait=False)


app = FastAPI(
    title="QuantPulse v2",
    description="Institutional-grade multi-strategy quantitative trading advisory system",
    version="2.0.0",
    lifespan=lifespan,
)

# ── Rate Limiting ──
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Middleware stack (order matters: last added = first executed) ──
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(ErrorTrackingMiddleware)
app.add_middleware(AuthMiddleware)

# ── CORS ──
allowed_origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ──
app.include_router(api_router)
app.include_router(ws_router)


@app.get("/health")
async def health():
    from backend.redis_client import redis_available
    from backend.websocket.manager import manager

    return {
        "status": "ok",
        "version": "2.0.0",
        "redis": redis_available(),
        "ws_clients": manager.client_count,
        "auth_enabled": settings.auth_enabled,
    }

"""Pipeline status, flow summary, and earnings calendar endpoints."""

from fastapi import APIRouter, Query

from backend.api.envelope import err, ok
from backend.data.cache import data_cache

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

PIPELINE_KEYS = [
    "pipeline:regime",
    "pipeline:scanner",
    "pipeline:sectors",
    "pipeline:portfolio",
    "pipeline:swing",
    "pipeline:flow",
    "pipeline:earnings_calendar",
]


@router.get("/status")
async def get_pipeline_status() -> dict:
    """Return the freshness of each pipeline cache entry."""
    status: dict[str, dict] = {}
    for key in PIPELINE_KEYS:
        short_name = key.replace("pipeline:", "")
        cached = data_cache.get(key)
        if cached and isinstance(cached, dict):
            status[short_name] = {
                "cached": True,
                "refreshed_at": cached.get("refreshed_at"),
            }
        else:
            status[short_name] = {"cached": False, "refreshed_at": None}
    return ok(status)


@router.post("/refresh")
async def trigger_pipeline_refresh() -> dict:
    """Manually trigger a full pipeline refresh (runs in background)."""
    import threading

    from backend.pipeline import refresh_all

    threading.Thread(target=refresh_all, daemon=True).start()
    return ok({"status": "started"})


@router.get("/flow")
async def get_flow_summary(
    refresh: bool = Query(False, description="Force live fetch from SteadyAPI"),
) -> dict:
    """Institutional options flow summary (SteadyAPI)."""
    if not refresh:
        cached = data_cache.get("pipeline:flow")
        if cached and isinstance(cached, dict):
            return ok(cached, cached=True)

    from backend.pipeline import refresh_flow

    result = refresh_flow()
    if not result:
        return err("flow_unavailable", "SteadyAPI disabled or unavailable", status=503)
    return ok(result)


@router.get("/earnings-calendar")
async def get_earnings_calendar(
    refresh: bool = Query(False, description="Force live fetch from FMP"),
) -> dict:
    """Upcoming earnings calendar (FMP)."""
    if not refresh:
        cached = data_cache.get("pipeline:earnings_calendar")
        if cached and isinstance(cached, dict):
            return ok(cached, cached=True)

    from backend.pipeline import refresh_earnings_calendar

    result = refresh_earnings_calendar()
    if not result:
        return err("earnings_unavailable", "FMP unavailable", status=503)
    return ok(result)

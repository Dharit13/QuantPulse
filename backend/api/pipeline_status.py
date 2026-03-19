"""Pipeline status, flow summary, and earnings calendar endpoints."""

from fastapi import APIRouter, Query

from backend.data.cache import data_cache

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

PIPELINE_KEYS = [
    "pipeline:regime", "pipeline:scanner", "pipeline:sectors",
    "pipeline:portfolio", "pipeline:swing", "pipeline:flow",
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
    return status


@router.post("/refresh")
async def trigger_pipeline_refresh() -> dict:
    """Manually trigger a full pipeline refresh (runs in background)."""
    import threading

    from backend.pipeline import refresh_all

    threading.Thread(target=refresh_all, daemon=True).start()
    return {"status": "started"}


@router.get("/flow")
async def get_flow_summary(
    refresh: bool = Query(False, description="Force live fetch from SteadyAPI"),
) -> dict:
    """Institutional options flow summary (SteadyAPI)."""
    if not refresh:
        cached = data_cache.get("pipeline:flow")
        if cached and isinstance(cached, dict):
            return cached

    from backend.pipeline import refresh_flow
    result = refresh_flow()
    return result or {"data": None, "refreshed_at": None, "error": "SteadyAPI disabled or unavailable"}


@router.get("/earnings-calendar")
async def get_earnings_calendar(
    refresh: bool = Query(False, description="Force live fetch from FMP"),
) -> dict:
    """Upcoming earnings calendar (FMP)."""
    if not refresh:
        cached = data_cache.get("pipeline:earnings_calendar")
        if cached and isinstance(cached, dict):
            return cached

    from backend.pipeline import refresh_earnings_calendar
    result = refresh_earnings_calendar()
    return result or {"data": [], "refreshed_at": None, "error": "FMP unavailable"}

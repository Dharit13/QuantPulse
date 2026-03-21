"""Error tracking API — view and manage tracked errors."""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request

from backend.models.database import get_supabase

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/errors", tags=["errors"])


@router.get("/recent")
async def get_recent_errors(limit: int = 50):
    """Return recent unresolved errors, grouped by type."""
    try:
        result = (
            get_supabase()
            .table("error_events")
            .select("*")
            .eq("resolved", False)
            .order("last_seen", desc=True)
            .limit(limit)
            .execute()
        )
        return {"errors": result.data or [], "count": len(result.data or [])}
    except Exception as e:
        logger.warning("Failed to fetch errors: %s", e)
        return {"errors": [], "count": 0}


@router.post("/{error_id}/resolve")
async def resolve_error(error_id: int):
    """Mark an error as resolved."""
    try:
        get_supabase().table("error_events").update({"resolved": True}).eq("id", error_id).execute()
        return {"status": "resolved"}
    except Exception as e:
        logger.warning("Failed to resolve error %d: %s", error_id, e)
        return {"status": "error", "detail": str(e)}


@router.post("/report")
async def report_frontend_error(request: Request):
    """Accept error reports from the frontend."""
    body = await request.json()
    from backend.middleware.error_tracking import _persist_error

    _persist_error(
        error_type=body.get("error_type", "FrontendError"),
        message=body.get("message", "Unknown frontend error")[:500],
        stack_trace=body.get("stack_trace", "")[:5000],
        request_path=body.get("url", ""),
        request_method="FRONTEND",
    )
    return {"status": "recorded"}


@router.post("/cleanup")
async def cleanup_old_errors(days: int = 30):
    """Delete resolved errors older than N days."""
    try:
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        get_supabase().table("error_events").delete().eq("resolved", True).lt("last_seen", cutoff).execute()
        return {"status": "cleaned"}
    except Exception as e:
        logger.warning("Error cleanup failed: %s", e)
        return {"status": "error", "detail": str(e)}

"""Error tracking middleware — persists unhandled exceptions to Supabase.

Captures stack traces, request context, and deduplicates by error_type + message.
Errors are also emitted as structured JSON logs (searchable in Railway).
"""

import logging
import traceback
from datetime import UTC, datetime

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger("backend.errors")


class ErrorTrackingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            return await call_next(request)
        except Exception as exc:
            error_type = type(exc).__name__
            message = str(exc)[:500]
            stack = traceback.format_exc()

            logger.error(
                "Unhandled %s: %s",
                error_type,
                message,
                extra={
                    "method": request.method,
                    "path": request.url.path,
                },
                exc_info=True,
            )

            _persist_error(
                error_type=error_type,
                message=message,
                stack_trace=stack,
                request_path=request.url.path,
                request_method=request.method,
            )

            return Response(
                status_code=500,
                content='{"detail":"Internal server error"}',
                media_type="application/json",
            )


def _persist_error(
    error_type: str,
    message: str,
    stack_trace: str,
    request_path: str = "",
    request_method: str = "",
    strategy: str | None = None,
) -> None:
    """Upsert error into Supabase error_events table (fire-and-forget)."""
    import threading

    def _write():
        try:
            from backend.models.database import get_supabase

            sb = get_supabase()
            now = datetime.now(UTC).isoformat()

            existing = (
                sb.table("error_events")
                .select("id,occurrence_count")
                .eq("error_type", error_type)
                .eq("message", message[:500])
                .eq("resolved", False)
                .limit(1)
                .execute()
            )

            if existing.data:
                record = existing.data[0]
                sb.table("error_events").update({
                    "occurrence_count": record["occurrence_count"] + 1,
                    "last_seen": now,
                    "stack_trace": stack_trace[:5000],
                    "request_path": request_path,
                    "request_method": request_method,
                }).eq("id", record["id"]).execute()
            else:
                sb.table("error_events").insert({
                    "error_type": error_type,
                    "message": message[:500],
                    "stack_trace": stack_trace[:5000],
                    "request_path": request_path,
                    "request_method": request_method,
                    "strategy": strategy,
                    "occurrence_count": 1,
                    "first_seen": now,
                    "last_seen": now,
                    "resolved": False,
                }).execute()
        except Exception as e:
            logger.debug("Failed to persist error event: %s", e)

    threading.Thread(target=_write, daemon=True).start()


def track_error(
    error_type: str,
    message: str,
    stack_trace: str = "",
    strategy: str | None = None,
) -> None:
    """Public helper for manually tracking errors from strategies/pipelines."""
    logger.error("%s: %s", error_type, message, extra={"strategy": strategy})
    _persist_error(
        error_type=error_type,
        message=message,
        stack_trace=stack_trace,
        strategy=strategy,
    )

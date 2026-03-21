"""Request logging middleware — logs every HTTP request as structured JSON.

Generates a unique request_id per request (propagated via contextvars)
so all log lines within a single request can be correlated.
"""

import logging
import time
import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from backend.logging_config import request_id_var

logger = logging.getLogger("backend.requests")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = uuid.uuid4().hex[:12]
        request_id_var.set(rid)
        request.state.request_id = rid

        start = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
            status = response.status_code if response else 500
            logger.info(
                "%s %s → %d (%.1fms)",
                request.method,
                request.url.path,
                status,
                elapsed_ms,
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status,
                    "duration_ms": elapsed_ms,
                },
            )

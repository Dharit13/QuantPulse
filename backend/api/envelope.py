"""Consistent API response envelope for all endpoints.

Every response follows: { data, meta, errors }
SSE streams are NOT wrapped — they use their own event format.
"""

from datetime import UTC, datetime

from fastapi.responses import JSONResponse

from backend.logging_config import request_id_var


def ok(data, cached: bool = False, **meta_extra) -> dict:
    """Wrap a successful response."""
    meta = {
        "request_id": request_id_var.get(""),
        "timestamp": datetime.now(UTC).isoformat(),
        "cached": cached,
        **meta_extra,
    }
    return {"data": data, "meta": meta, "errors": None}


def err(code: str, message: str, status: int = 400) -> JSONResponse:
    """Return an error response with proper HTTP status."""
    body = {
        "data": None,
        "meta": {
            "request_id": request_id_var.get(""),
            "timestamp": datetime.now(UTC).isoformat(),
        },
        "errors": [{"code": code, "message": message}],
    }
    return JSONResponse(status_code=status, content=body)

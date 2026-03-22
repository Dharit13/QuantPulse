"""Supabase JWT authentication middleware.

Feature-flagged via AUTH_ENABLED (default False).
When enabled, validates the Supabase JWT from the Authorization header
and attaches user_id to request.state.
"""

import logging

import jwt
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from backend.config import settings

logger = logging.getLogger(__name__)

_PUBLIC_PATHS = frozenset({"/health", "/docs", "/redoc", "/openapi.json"})


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not settings.auth_enabled:
            request.state.user_id = None
            return await call_next(request)

        path = request.url.path
        if path in _PUBLIC_PATHS or path.startswith("/ws"):
            request.state.user_id = None
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return Response(
                status_code=401, content='{"detail":"Missing authorization token"}', media_type="application/json"
            )

        token = auth_header[7:]
        try:
            payload = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
            )
            request.state.user_id = payload.get("sub")
        except jwt.ExpiredSignatureError:
            return Response(status_code=401, content='{"detail":"Token expired"}', media_type="application/json")
        except jwt.InvalidTokenError as e:
            logger.warning("Invalid JWT: %s", e)
            return Response(status_code=401, content='{"detail":"Invalid token"}', media_type="application/json")

        return await call_next(request)

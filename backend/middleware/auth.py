"""Supabase JWT authentication middleware.

Feature-flagged via AUTH_ENABLED (default False).
When enabled, validates the Supabase JWT from the Authorization header
and attaches user_id to request.state.

Supports RS256 (asymmetric) tokens issued by Supabase via JWKS discovery,
with a fallback to HS256 (symmetric) for backward compatibility.
"""

import logging
from typing import Any

import jwt
from fastapi import Request, Response
from jwt import PyJWKClient
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from backend.config import settings

logger = logging.getLogger(__name__)

_PUBLIC_PATHS = frozenset({"/health", "/docs", "/redoc", "/openapi.json"})

_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        url = settings.supabase_url.rstrip("/") + "/auth/v1/.well-known/jwks.json"
        _jwks_client = PyJWKClient(url, cache_keys=True, lifespan=3600)
        logger.info("JWKS client initialized for %s", url)
    return _jwks_client


def _decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a Supabase JWT (RS256 via JWKS or HS256 fallback)."""
    header = jwt.get_unverified_header(token)
    alg = header.get("alg", "HS256")

    if alg != "HS256":
        try:
            signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
            return jwt.decode(token, signing_key.key, algorithms=[alg], audience="authenticated")
        except Exception as exc:
            logger.warning("JWKS decode failed (alg=%s): %s — trying HS256 fallback", alg, exc)

    return jwt.decode(
        token,
        settings.supabase_jwt_secret,
        algorithms=["HS256"],
        audience="authenticated",
    )


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
            payload = _decode_token(token)
            request.state.user_id = payload.get("sub")
        except jwt.ExpiredSignatureError:
            return Response(status_code=401, content='{"detail":"Token expired"}', media_type="application/json")
        except jwt.InvalidTokenError as e:
            logger.warning("Invalid JWT: %s", e)
            return Response(status_code=401, content='{"detail":"Invalid token"}', media_type="application/json")

        return await call_next(request)

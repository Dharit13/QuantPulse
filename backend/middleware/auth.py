"""Supabase JWT authentication middleware.

Feature-flagged via AUTH_ENABLED (default False).
When enabled, validates the Supabase JWT from the Authorization header
and attaches user_id to request.state.

Supports RS256 (asymmetric) tokens issued by Supabase via JWKS discovery,
with a fallback to HS256 (symmetric) for backward compatibility.
"""

import logging
import time
from typing import Any

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from backend.config import settings

logger = logging.getLogger(__name__)

_PUBLIC_PATHS = frozenset({"/health", "/docs", "/redoc", "/openapi.json"})

# JWKS cache: stores {"keys": [...]} payload and the monotonic timestamp it was fetched.
_JWKS_CACHE: dict[str, Any] = {}
_JWKS_FETCHED_AT: float = 0.0
_JWKS_TTL: float = 3600.0  # 1 hour

# Derived from the Supabase project URL in settings.
_JWKS_URL = "https://xrsspsuiyzgyjaqrcbrc.supabase.co/.well-known/jwks.json"


async def _get_jwks() -> dict[str, Any]:
    """Return the cached JWKS, refreshing if the TTL has elapsed."""
    global _JWKS_CACHE, _JWKS_FETCHED_AT

    now = time.monotonic()
    if _JWKS_CACHE and (now - _JWKS_FETCHED_AT) < _JWKS_TTL:
        return _JWKS_CACHE

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(_JWKS_URL)
            response.raise_for_status()
            _JWKS_CACHE = response.json()
            _JWKS_FETCHED_AT = now
            logger.debug("JWKS refreshed from %s", _JWKS_URL)
    except Exception as exc:
        logger.warning("Failed to fetch JWKS from %s: %s", _JWKS_URL, exc)
        # Return the stale cache if available, otherwise an empty set.
        if _JWKS_CACHE:
            logger.warning("Using stale JWKS cache due to fetch failure")
        # If we have nothing cached, callers will fall back to HS256.

    return _JWKS_CACHE


def _public_key_for_kid(jwks: dict[str, Any], kid: str) -> Any | None:
    """Find the JWK matching *kid* and return the corresponding RSA public key."""
    for jwk in jwks.get("keys", []):
        if jwk.get("kid") == kid:
            try:
                return RSAAlgorithm.from_jwk(jwk)
            except Exception as exc:
                logger.warning("Failed to parse JWK for kid=%s: %s", kid, exc)
                return None
    return None


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
            payload = await _decode_token(token)
            request.state.user_id = payload.get("sub")
        except jwt.ExpiredSignatureError:
            return Response(status_code=401, content='{"detail":"Token expired"}', media_type="application/json")
        except jwt.InvalidTokenError as e:
            logger.warning("Invalid JWT: %s", e)
            return Response(status_code=401, content='{"detail":"Invalid token"}', media_type="application/json")

        return await call_next(request)


async def _decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT, preferring RS256 via JWKS and falling back to HS256.

    Raises jwt.InvalidTokenError (or a subclass) on any validation failure.
    """
    # Peek at the header without verifying the signature yet.
    try:
        header = jwt.get_unverified_header(token)
    except jwt.DecodeError as exc:
        raise jwt.InvalidTokenError(f"Malformed JWT header: {exc}") from exc

    alg = header.get("alg", "")
    kid = header.get("kid")

    # ── RS256 path ────────────────────────────────────────────────────────────
    if alg == "RS256" and kid:
        jwks = await _get_jwks()
        public_key = _public_key_for_kid(jwks, kid)

        if public_key is not None:
            return jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                audience="authenticated",
            )

        # kid not found in JWKS — log and fall through to HS256 as last resort.
        logger.warning("No JWK found for kid=%s; attempting HS256 fallback", kid)

    # ── HS256 fallback ────────────────────────────────────────────────────────
    if settings.supabase_jwt_secret:
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )

    raise jwt.InvalidTokenError(
        f"Cannot validate token with alg={alg!r}: no matching public key and no JWT secret configured"
    )

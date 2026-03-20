"""Supabase client — thread-local instances to avoid HTTP/2 connection issues."""

import logging
import threading

from supabase import Client, create_client

from backend.config import settings

logger = logging.getLogger(__name__)

_local = threading.local()


def get_supabase() -> Client:
    """Return a thread-local Supabase client, creating one per thread."""
    client = getattr(_local, "client", None)
    if client is None:
        if not settings.supabase_url or not settings.supabase_key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_KEY must be set in .env. "
                "Get them from Supabase Dashboard > Project Settings > API."
            )
        client = create_client(settings.supabase_url, settings.supabase_key)
        _local.client = client
        logger.info("Supabase client initialized (thread=%s)", threading.current_thread().name)
    return client


def reset_client() -> None:
    """Force a new client on the current thread (use after connection errors)."""
    _local.client = None

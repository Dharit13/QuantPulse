"""API integration test fixtures — TestClient with mocked externals."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


class FakeSupabaseTable:
    """Minimal mock for supabase.table(...).select(...).execute() chains."""

    def __init__(self, data=None):
        self._data = data or []

    def select(self, *args, **kwargs):
        return self

    def insert(self, *args, **kwargs):
        return self

    def update(self, *args, **kwargs):
        return self

    def upsert(self, *args, **kwargs):
        return self

    def delete(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def neq(self, *args, **kwargs):
        return self

    def lt(self, *args, **kwargs):
        return self

    def gt(self, *args, **kwargs):
        return self

    def in_(self, *args, **kwargs):
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def execute(self):
        return MagicMock(data=self._data)


class FakeSupabase:
    """Minimal Supabase client mock."""

    def table(self, name: str):
        return FakeSupabaseTable()


@pytest.fixture
def mock_supabase():
    fake = FakeSupabase()
    with patch("backend.models.database.get_supabase", return_value=fake):
        yield fake


@pytest.fixture
def mock_scheduler():
    with patch("backend.scheduler.register_all_jobs"):
        yield


@pytest.fixture
def mock_redis():
    with patch("backend.redis_client.get_redis", return_value=None), \
         patch("backend.redis_client.redis_available", return_value=False):
        yield


@pytest.fixture
def client(mock_supabase, mock_scheduler, mock_redis):
    """TestClient with all externals mocked."""
    with patch("backend.websocket.manager.manager.start_redis_listener"):
        from backend.main import app
        with TestClient(app) as c:
            yield c


@pytest.fixture
def auth_client(mock_supabase, mock_scheduler, mock_redis):
    """TestClient with auth enabled."""
    with patch("backend.config.settings.auth_enabled", True), \
         patch("backend.config.settings.supabase_jwt_secret", "test-secret"), \
         patch("backend.websocket.manager.manager.start_redis_listener"):
        from backend.main import app
        with TestClient(app) as c:
            yield c

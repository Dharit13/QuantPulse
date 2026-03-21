"""API integration test fixtures — TestClient with mocked externals."""

from unittest.mock import MagicMock, patch

import pytest


class FakeSupabaseTable:
    """Minimal mock for supabase.table(...).select(...).execute() chains."""

    def __init__(self, data=None):
        self._data = data or []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *a, **kw: self

    def execute(self):
        return MagicMock(data=self._data)


class FakeSupabase:
    def table(self, name: str):
        return FakeSupabaseTable()


_patches = []


def _start_patches():
    """Start all patches before importing the app."""
    global _patches
    p = [
        patch.dict("sys.modules", {"redis": MagicMock()}),
    ]
    for pp in p:
        pp.start()
        _patches.append(pp)


def _stop_patches():
    for pp in _patches:
        pp.stop()
    _patches.clear()


@pytest.fixture
def client():
    """TestClient with all externals mocked."""
    import backend.redis_client as rc

    orig_get = rc.get_redis
    orig_avail = rc.redis_available
    rc.get_redis = lambda: None
    rc._available = False
    rc.redis_available = lambda: False

    import backend.models.database as db

    fake_sb = FakeSupabase()
    orig_sb = db.get_supabase
    db.get_supabase = lambda: fake_sb

    import backend.scheduler as sched

    orig_register = sched.register_all_jobs
    sched.register_all_jobs = lambda s: None

    from backend.websocket.manager import manager

    async def _noop_listener():
        pass

    orig_start = manager.start_redis_listener
    manager.start_redis_listener = _noop_listener

    from fastapi.testclient import TestClient

    from backend.main import app

    with TestClient(app) as c:
        yield c

    rc.get_redis = orig_get
    rc.redis_available = orig_avail
    rc._available = None
    db.get_supabase = orig_sb
    sched.register_all_jobs = orig_register
    manager.start_redis_listener = orig_start


@pytest.fixture
def auth_client():
    """TestClient with auth enabled."""
    import backend.config as cfg
    import backend.redis_client as rc

    orig_get = rc.get_redis
    orig_avail = rc.redis_available
    rc.get_redis = lambda: None
    rc._available = False
    rc.redis_available = lambda: False

    import backend.models.database as db

    fake_sb = FakeSupabase()
    orig_sb = db.get_supabase
    db.get_supabase = lambda: fake_sb

    import backend.scheduler as sched

    orig_register = sched.register_all_jobs
    sched.register_all_jobs = lambda s: None

    from backend.websocket.manager import manager

    async def _noop_listener():
        pass

    orig_start = manager.start_redis_listener
    manager.start_redis_listener = _noop_listener

    orig_auth = cfg.settings.auth_enabled
    orig_jwt = cfg.settings.supabase_jwt_secret
    cfg.settings.auth_enabled = True
    cfg.settings.supabase_jwt_secret = "test-secret"

    from fastapi.testclient import TestClient

    from backend.main import app

    with TestClient(app) as c:
        yield c

    cfg.settings.auth_enabled = orig_auth
    cfg.settings.supabase_jwt_secret = orig_jwt
    rc.get_redis = orig_get
    rc.redis_available = orig_avail
    rc._available = None
    db.get_supabase = orig_sb
    sched.register_all_jobs = orig_register
    manager.start_redis_listener = orig_start

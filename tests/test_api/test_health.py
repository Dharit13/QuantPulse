"""Integration tests for the /health endpoint."""


class TestHealth:
    def test_health_returns_200(self, client):
        res = client.get("/health")
        assert res.status_code == 200

    def test_health_has_envelope(self, client):
        body = client.get("/health").json()
        assert "data" in body
        assert "meta" in body
        assert "errors" in body

    def test_health_data_fields(self, client):
        data = client.get("/health").json()["data"]
        assert data["status"] == "ok"
        assert "version" in data
        assert "redis" in data
        assert "ws_clients" in data
        assert "auth_enabled" in data

    def test_health_meta_fields(self, client):
        meta = client.get("/health").json()["meta"]
        assert "request_id" in meta
        assert "timestamp" in meta

    def test_health_errors_null(self, client):
        body = client.get("/health").json()
        assert body["errors"] is None

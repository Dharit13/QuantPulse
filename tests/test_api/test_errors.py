"""Integration tests for the /errors endpoints."""


class TestErrorsRecent:
    def test_returns_200(self, client):
        res = client.get("/api/v1/errors/recent")
        assert res.status_code == 200

    def test_has_errors_list(self, client):
        data = client.get("/api/v1/errors/recent").json()["data"]
        assert "errors" in data
        assert "count" in data
        assert isinstance(data["errors"], list)


class TestErrorReport:
    def test_report_frontend_error(self, client):
        res = client.post(
            "/api/v1/errors/report",
            json={
                "error_type": "TestError",
                "message": "Test error from integration test",
                "stack_trace": "at test.js:1",
                "url": "/test-page",
            },
        )
        assert res.status_code == 200
        assert res.json()["data"]["status"] == "recorded"


class TestErrorCleanup:
    def test_cleanup_returns_200(self, client):
        res = client.post("/api/v1/errors/cleanup?days=30")
        assert res.status_code == 200

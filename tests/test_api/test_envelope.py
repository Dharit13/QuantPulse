"""Integration tests verifying the response envelope shape across endpoints."""


def _assert_envelope(body: dict) -> None:
    assert "data" in body, f"Missing 'data' key in {list(body.keys())}"
    assert "meta" in body, f"Missing 'meta' key in {list(body.keys())}"
    assert "errors" in body, f"Missing 'errors' key in {list(body.keys())}"
    assert isinstance(body["meta"], dict)
    assert "request_id" in body["meta"]
    assert "timestamp" in body["meta"]


class TestEnvelopeShape:
    def test_health_envelope(self, client):
        _assert_envelope(client.get("/health").json())

    def test_regime_envelope(self, client):
        res = client.get("/api/v1/regime/current")
        body = res.json()
        _assert_envelope(body)

    def test_news_envelope(self, client):
        res = client.get("/api/v1/news/market")
        body = res.json()
        _assert_envelope(body)

    def test_errors_recent_envelope(self, client):
        res = client.get("/api/v1/errors/recent")
        body = res.json()
        _assert_envelope(body)

    def test_pipeline_status_envelope(self, client):
        res = client.get("/api/v1/pipeline/status")
        body = res.json()
        _assert_envelope(body)

    def test_backtest_status_envelope(self, client):
        res = client.get("/api/v1/backtest/status")
        body = res.json()
        _assert_envelope(body)


class TestUniqueRequestIds:
    def test_request_ids_are_unique(self, client):
        ids = set()
        for _ in range(5):
            meta = client.get("/health").json()["meta"]
            ids.add(meta["request_id"])
        assert len(ids) == 5


class TestTimestamp:
    def test_timestamp_is_iso(self, client):
        from datetime import datetime

        ts = client.get("/health").json()["meta"]["timestamp"]
        datetime.fromisoformat(ts)

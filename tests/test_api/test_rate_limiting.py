"""Integration tests for rate limiting."""


class TestRateLimiting:
    def test_health_not_rate_limited_quickly(self, client):
        for _ in range(10):
            res = client.get("/health")
            assert res.status_code == 200

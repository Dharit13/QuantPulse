"""Integration tests for authentication middleware."""

import jwt


class TestAuthDisabled:
    def test_no_token_returns_200(self, client):
        res = client.get("/health")
        assert res.status_code == 200

    def test_api_without_token_returns_200(self, client):
        res = client.get("/api/v1/pipeline/status")
        assert res.status_code == 200


class TestAuthEnabled:
    def test_no_token_returns_401(self, auth_client):
        res = auth_client.get("/api/v1/pipeline/status")
        assert res.status_code == 401

    def test_invalid_token_returns_401(self, auth_client):
        res = auth_client.get(
            "/api/v1/pipeline/status",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert res.status_code == 401

    def test_health_always_200(self, auth_client):
        res = auth_client.get("/health")
        assert res.status_code == 200

    def test_valid_token_returns_200(self, auth_client):
        token = jwt.encode(
            {"sub": "test-user-id", "aud": "authenticated"},
            "test-secret",
            algorithm="HS256",
        )
        res = auth_client.get(
            "/api/v1/pipeline/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200

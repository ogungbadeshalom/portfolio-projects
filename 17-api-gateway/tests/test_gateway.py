"""Integration tests for the multi-tenant API gateway.

Exercises REAL behaviour through FastAPI's TestClient:
* regist / login / JWT
* API key create / list / revoke
* HMAC key verification (rejects wrong/unknown keys with 401)
* the /v1/* proxy (in-process echo backend) with rate-limit headers
* per-tenant sliding-window rate limiting (429 + Retry-After)
* monthly quota enforcement (402)
* usage logging + GET /api/usage
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.conftest import create_key, make_echo_request, register_login


class TestAuth:
    def test_register_and_login(self, app_factory):
        app = app_factory()
        client = TestClient(app)
        r = client.post("/api/auth/register", json={"email": "a@b.com", "password": "secret1"})
        assert r.status_code in (200, 201)
        assert r.json()["email"] == "a@b.com"

        login = client.post("/api/auth/login", json={"email": "a@b.com", "password": "secret1"})
        assert login.status_code == 200
        assert login.json()["token"]

    def test_register_duplicate_email_conflict(self, app_factory):
        app = app_factory()
        client = TestClient(app)
        body = {"email": "dup@x.com", "password": "password"}
        assert client.post("/api/auth/register", json=body).status_code in (200, 201)
        assert client.post("/api/auth/register", json=body).status_code == 409

    def test_login_wrong_password(self, app_factory):
        app = app_factory()
        client = TestClient(app)
        client.post("/api/auth/register", json={"email": "u@x.com", "password": "goodpass"})
        bad = client.post("/api/auth/login", json={"email": "u@x.com", "password": "wrongpass"})
        assert bad.status_code == 401


class TestKeys:
    def test_create_and_list_key(self, built_app):
        client = built_app["client"]
        keys = client.get("/api/keys", headers={"Authorization": "Bearer " + built_app["token"]})
        assert keys.status_code == 200
        assert built_app["key"].startswith("sk_live_")
        assert any(k["prefix"] == "sk_live_" for k in keys.json())

    def test_revoke_key_invalidates_it(self, built_app):
        client = built_app["client"]
        token = built_app["token"]
        key = built_app["key"]
        # key works before revocation
        assert make_echo_request(client, key).status_code == 200

        key_id = client.get("/api/keys", headers={"Authorization": f"Bearer {token}"}).json()[0]["id"]
        rev = client.delete(f"/api/keys/{key_id}", headers={"Authorization": f"Bearer {token}"})
        assert rev.status_code == 200
        # revoked key is now rejected with 401
        assert make_echo_request(client, key).status_code == 401

    def test_keys_require_auth(self, built_app):
        client = built_app["client"]
        assert client.post("/api/keys", headers={}, json={"name": "x"}).status_code == 401
        assert client.get("/api/keys", headers={}).status_code == 401


class TestProxyAuth:
    def test_missing_key_returns_401_with_header(self, built_app):
        resp = built_app["client"].get("/v1/ping")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "invalid_api_key"
        assert "API-Key" in resp.headers.get("WWW-Authenticate", "")

    def test_unknown_key_returns_401(self, built_app):
        resp = built_app["client"].get("/v1/ping", headers={"X-API-Key": "sk_live_bogus"})
        assert resp.status_code == 401

    def test_valid_key_proxies_to_backend(self, built_app):
        key = built_app["key"]
        resp = make_echo_request(built_app["client"], key, path="/v1/hello", body=b"world")
        assert resp.status_code == 200
        data = resp.json()
        assert data["method"] == "GET"
        # The gateway proxies the path under /v1/ to the backend (strips the
        # API-key namespace), so the backend sees /hello.
        assert data["path"] == "/hello"
        # Backend-specific header passed through.
        assert resp.headers.get("x-backend") == "echo"
        # Rate-limit headers always present on /v1/* responses.
        assert "X-RateLimit-Limit" in resp.headers
        assert "X-RateLimit-Remaining" in resp.headers

    def test_post_body_is_proxied(self, built_app):
        key = built_app["key"]
        resp = built_app["client"].post("/v1/data", content=b'{"a":1}', headers={"X-API-Key": key})
        assert resp.status_code == 200
        assert resp.json()["body_utf8"] == '{"a":1}'


class TestRateLimit:
    def test_rate_limited_returns_429(self, app_factory):
        app = app_factory(rate_limit=3, rate_window=60)
        client = TestClient(app)
        token = register_login(app, client)
        key = create_key(client, token)

        # First 3 requests allowed.
        assert make_echo_request(client, key).status_code == 200
        assert make_echo_request(client, key).status_code == 200
        assert make_echo_request(client, key).status_code == 200
        # 4th exceeds the sliding-window limit.
        resp = make_echo_request(client, key)
        assert resp.status_code == 429
        body = resp.json()["error"]
        assert body["code"] == "rate_limited"
        assert "Retry-After" in resp.headers

    def test_rate_limit_headers_decline(self, app_factory):
        app = app_factory(rate_limit=5, rate_window=60)
        client = TestClient(app)
        token = register_login(app, client)
        key = create_key(client, token)
        make_echo_request(client, key)
        resp = make_echo_request(client, key)
        # Remaining decreases from 4 after first use.
        assert int(resp.headers["X-RateLimit-Remaining"]) <= 4
        assert resp.headers["X-RateLimit-Limit"] == "5"


class TestQuota:
    def test_quota_exceeded_returns_402(self, app_factory):
        app = app_factory()
        client = TestClient(app)
        token = register_login(app, client)
        key = create_key(client, token)

        # Simulate a tenant already past its free-plan quota (1000/mo).
        from gateway import usage

        for _ in range(1100):
            usage.log_usage(1, "/v1/past", "GET", 200, 5)
        # Flush with a cap above the buffered count so the whole row-set lands.
        usage.get_batcher().flush_now(max_rows=2000)

        resp = make_echo_request(client, key)
        assert resp.status_code == 402
        assert resp.json()["error"]["code"] == "quota_exceeded"
        assert "upgrade" in resp.headers.get("Link", "")

    def test_within_quota_is_allowed(self, built_app):
        key = built_app["key"]
        assert make_echo_request(built_app["client"], key).status_code == 200


class TestUsage:
    def test_usage_stats_after_proxying(self, built_app):
        client = built_app["client"]
        key = built_app["key"]
        for _ in range(3):
            make_echo_request(client, key, path="/v1/metrics")
        from gateway import usage

        usage.flush_now()
        stats = client.get("/api/usage", headers={"Authorization": "Bearer " + built_app["token"]})
        assert stats.status_code == 200
        assert stats.json()["total_requests"] >= 3

    def test_tenant_isolation(self, app_factory):
        app = app_factory()
        client = TestClient(app)
        # Two tenants, each with their own usage.
        token1 = register_login(app, client, email="one@x.com", password="password")
        token2 = register_login(app, client, email="two@x.com", password="password")
        key1 = create_key(client, token1, name="k1")
        key2 = create_key(client, token2, name="k2")
        make_echo_request(client, key1, path="/v1/a")
        from gateway import usage

        usage.flush_now()
        u1 = client.get("/api/usage", headers={"Authorization": "Bearer " + token1}).json()
        u2 = client.get("/api/usage", headers={"Authorization": "Bearer " + token2}).json()
        assert u1["total_requests"] == 1
        assert u2["total_requests"] == 0


class TestHealth:
    def test_health(self, built_app):
        assert built_app["client"].get("/health").json()["status"] == "ok"
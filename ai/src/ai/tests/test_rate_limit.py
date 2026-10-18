"""The general API rate limit (core/rate_limit.py)."""
import jwt
import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from src.ai.core.rate_limit import RateLimitMiddleware


class FakeRedis:
    def __init__(self, broken=False):
        self.counts, self.broken = {}, broken

    def pipeline(self):
        if self.broken:
            raise ConnectionError("redis down")
        redis, ops = self, []

        class Pipe:
            def incr(self, key):
                ops.append(key)

            def expire(self, key, seconds):
                pass

            def execute(self):
                result = []
                for key in ops:
                    redis.counts[key] = redis.counts.get(key, 0) + 1
                    result += [redis.counts[key], True]
                return result
        return Pipe()


def _app(redis, clock):
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, redis_factory=lambda: redis, clock=clock)
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"],
                       expose_headers=["Retry-After"])
    for path in ("/products", "/health", "/billing/webhook"):
        app.add_api_route(path, lambda: {"ok": True}, methods=["GET", "POST"])
    return app


@pytest.fixture
def limits(monkeypatch):
    monkeypatch.setenv("API_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("API_RATE_LIMIT_PER_COMPANY_PER_MINUTE", "5")
    monkeypatch.setenv("API_RATE_LIMIT_PER_IP_PER_MINUTE", "3")
    monkeypatch.setenv("JWT_SECRET", "rate-limit-test-secret")


def _token(tenant):
    return {"Authorization": "Bearer " + jwt.encode({"tenant_id": tenant, "user_id": "u"}, "rate-limit-test-secret", algorithm="HS256")}


def test_each_company_has_its_own_budget_and_gets_retry_after(limits):
    now = [1_000_000 * 60 + 15.0]
    client = TestClient(_app(FakeRedis(), lambda: now[0]))
    for _ in range(5):
        assert client.get("/products", headers=_token("a")).status_code == 200
    blocked = client.get("/products", headers={**_token("a"), "Origin": "http://localhost:5173"})
    assert blocked.status_code == 429 and blocked.headers["Retry-After"] == "45"
    assert blocked.headers["access-control-allow-origin"] == "http://localhost:5173", "the browser can read the 429"
    assert client.get("/products", headers=_token("b")).status_code == 200, "another company is unaffected"
    now[0] += 60
    assert client.get("/products", headers=_token("a")).status_code == 200, "the next minute starts afresh"


def test_anonymous_requests_are_limited_per_address(limits, monkeypatch):
    client = TestClient(_app(FakeRedis(), lambda: 60.0))
    assert [client.post("/products").status_code for _ in range(4)] == [200, 200, 200, 429]
    # Behind a trusted proxy the last X-Forwarded-For entry is the client.
    monkeypatch.setenv("API_TRUST_FORWARDED_FOR", "true")
    assert client.post("/products", headers={"X-Forwarded-For": "1.1.1.1, 9.9.9.9"}).status_code == 200


def test_invalid_tokens_count_against_the_address(limits):
    client = TestClient(_app(FakeRedis(), lambda: 60.0))
    codes = [client.get("/products", headers={"Authorization": "Bearer forged"}).status_code for _ in range(4)]
    assert codes[-1] == 429


def test_health_webhook_and_preflight_are_never_limited(limits):
    client = TestClient(_app(FakeRedis(), lambda: 60.0))
    for _ in range(10):
        assert client.get("/health").status_code == 200
        assert client.post("/billing/webhook").status_code == 200
        assert client.options("/products", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"}).status_code == 200


def test_fails_open_without_redis(limits):
    client = TestClient(_app(FakeRedis(broken=True), lambda: 60.0))
    assert all(client.get("/products").status_code == 200 for _ in range(10))


def test_can_be_switched_off(limits, monkeypatch):
    monkeypatch.setenv("API_RATE_LIMIT_ENABLED", "false")
    client = TestClient(_app(FakeRedis(), lambda: 60.0))
    assert all(client.post("/products").status_code == 200 for _ in range(10))

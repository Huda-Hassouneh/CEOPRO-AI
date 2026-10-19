import os

# Live-DB tests connect to localhost over TCP; libpq's GSSAPI probe occasionally gets garbage back through
# container port proxies ("invalid response to GSSAPI negotiation") and fails an otherwise good connection.
os.environ.setdefault("PGGSSENCMODE", "disable")

# One JWT secret for the whole run: core/security.py reads it once at import,
# so every test file must sign tokens with this same value.
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests")

# No background forecast threads outliving a test (forecasting/refresh.py).
os.environ.setdefault("FORECAST_AUTO_REFRESH", "0")
os.environ.setdefault("DISCOVERY_REFRESH_ENABLED", "0")
os.environ.setdefault("NOTIFICATION_DIGEST_ENABLED", "0")
os.environ.setdefault("BILLING_MAINTENANCE_ENABLED", "0")
os.environ.setdefault("API_RATE_LIMIT_ENABLED", "false")  # test_rate_limit.py turns it on
# Discovery tests never fetch real competitor websites.
os.environ.setdefault("DISCOVERY_ENRICH_MAX_SITES", "0")
# Model loaders are mocked in tests: skip the hub reachability probe.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
# Onboarding's connect endpoints refuse (503) without a credential-vault key;
# give unit tests a throwaway one so they don't depend on the developer's shell.
os.environ.setdefault("CREDENTIAL_VAULT_KMS_BACKEND", "local")
os.environ.setdefault("CREDENTIAL_VAULT_MASTER_KEY", "x6M1l3m0V0kq0cV8k2Yb3m1c1ZkQe0Qm9d7mP2l1nQ4=")
# Tests written before plan assignments existed create companies directly:
# give them the default plan. Billing tests set "none" (production) themselves.
os.environ.setdefault("UNASSIGNED_PLAN_ACCESS", "default")
# Provider tests mock HTTP without a database; the credit tests turn metering
# back on (billing/credits.py honours this only under pytest).
os.environ.setdefault("KEEL_TEST_DISABLE_METERING", "1")

import time

import pytest

from src.ai.core import auth_throttle


class _InMemoryRedis:
    """Just the commands auth_throttle uses, with real expiry - so tests
    never depend on (or leave counters in) a real Redis."""

    def __init__(self):
        self._data, self._expiry = {}, {}

    def _alive(self, key):
        if key in self._expiry and self._expiry[key] <= time.monotonic():
            self._data.pop(key, None)
            self._expiry.pop(key, None)
        return key in self._data

    def get(self, key):
        return str(self._data[key]) if self._alive(key) else None

    def incr(self, key):
        self._data[key] = (self._data[key] if self._alive(key) else 0) + 1
        return self._data[key]

    def expire(self, key, seconds):
        self._expiry[key] = time.monotonic() + seconds

    def ttl(self, key):
        return max(0, int(self._expiry[key] - time.monotonic())) if self._alive(key) and key in self._expiry else -1

    def set(self, key, value, ex=None):
        self._data[key] = value
        if ex:
            self._expiry[key] = time.monotonic() + ex
        return True

    def exists(self, key):
        return 1 if self._alive(key) else 0

    def delete(self, key):
        self._data.pop(key, None)
        self._expiry.pop(key, None)


@pytest.fixture(autouse=True)
def _isolated_signed_out_tokens(monkeypatch):
    """Signed-out tokens live in an in-memory store per test, never a real Redis."""
    from src.ai.core import security

    fake = _InMemoryRedis()
    monkeypatch.setattr(security, "_revocation_store", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def _fresh_tenant_cache():
    """Each test starts with no cached read models (core/tenant_cache.py),
    so data a test writes straight into the database is never hidden by a
    view another test cached."""
    from src.ai.core import tenant_cache

    tenant_cache.clear()
    yield
    tenant_cache.clear()


@pytest.fixture(autouse=True)
def _isolated_auth_throttle(monkeypatch):
    fake = _InMemoryRedis()
    monkeypatch.setattr(auth_throttle, "_redis", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def _no_plan_limits_for_mocked_connections(request, monkeypatch):
    """Router/unit tests run on MagicMock connections, which can't answer
    the usage queries; plan enforcement itself is covered against a real
    database in test_usage_integration_db.py (left unpatched)."""
    if request.module.__name__.endswith(("test_usage_integration_db", "test_billing_integration_db",
                                          "test_plan_catalog_integration_db", "test_credits_integration_db",
                                          "test_subscription_limits_integration_db")):
        return
    from src.ai.core import entitlements, usage
    monkeypatch.setattr(usage, "reserve", lambda conn, tenant_id, feature_code, amount=1: {
        "tenant_id": tenant_id, "feature_code": feature_code, "period_start": None, "amount": amount})
    monkeypatch.setattr(usage, "release", lambda conn, reservation: None)
    monkeypatch.setattr(usage, "ensure_capacity", lambda conn, tenant_id, feature_code, adding=1: None)
    monkeypatch.setattr(usage, "capacity_left", lambda conn, tenant_id, feature_code: None)
    monkeypatch.setattr(usage, "ensure_ai_rate", lambda tenant_id: None)
    monkeypatch.setattr(usage, "remaining", lambda conn, tenant_id, feature_code: None)
    monkeypatch.setattr(usage, "settle", lambda conn, reservation, actual: None)
    monkeypatch.setattr(usage, "record", lambda conn, tenant_id, feature_code, amount: None)
    monkeypatch.setattr(usage, "require_entitlement", lambda conn, tenant_id, feature_code: None)
    monkeypatch.setattr(entitlements, "_plan", lambda tenant_id, user_id: {
        "status": "active", "entitlements": {usage.MARKET_INTELLIGENCE, usage.DEMAND_PREDICTION, usage.COMPETITOR_MANAGEMENT}})


@pytest.fixture(autouse=True)
def _models_obtainable_by_default(request, monkeypatch):
    """Tests inject their own fake models; the real availability probe (which
    says "unavailable" offline when weights aren't cached) is exercised by
    the tests that target it directly."""
    from src.ai.core import ml_runtime

    ml_runtime._UNOBTAINABLE_UNTIL.clear()
    if "model_obtainable" in request.module.__name__ or request.node.get_closest_marker("real_model_probe"):
        return
    monkeypatch.setattr(ml_runtime, "model_obtainable", lambda *a, **k: True)


@pytest.fixture(autouse=True)
def _connector_hosts_are_mocked(monkeypatch):
    """Connector tests use made-up hostnames with the network mocked; the
    public-address check (network_security.assert_connector_target) has
    its own tests that remove this."""
    monkeypatch.setenv("CONNECTORS_ALLOW_PRIVATE_HOSTS", "true")


@pytest.fixture(autouse=True)
def _no_live_ai_hints_in_discovery(monkeypatch):
    """Discovery asks the configured AI model for specialty words, product
    aliases and category words; tests pass their own answers instead."""
    monkeypatch.setenv("DISCOVERY_AI_HINTS", "false")

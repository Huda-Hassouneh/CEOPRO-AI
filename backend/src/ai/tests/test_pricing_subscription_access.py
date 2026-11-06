"""HTTP regression tests for subscription-only local pricing access.

Database/plan reads are controlled here; pricing math and native tenant/RLS
behavior have their own focused suites. No provider or live recommendation runs.
"""
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ai.core.exceptions import register_exception_handlers
from src.ai.core.security import TenantContext, get_tenant_context
from src.ai.routers import pricing


REAL_RECOMMEND = pricing.pricing_pipeline.run_price_recommendation
TENANT = "00000000-0000-0000-0000-000000000011"
ACTOR = "00000000-0000-0000-0000-000000000012"
PRODUCT = "00000000-0000-0000-0000-000000000013"
RESULT = {"status": "OK", "evidence_id": "synthetic-evidence"}


@pytest.fixture
def endpoint(monkeypatch):
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    connection = MagicMock(return_value=conn)
    monkeypatch.setattr(pricing.db, "app_role_connection", connection)
    plan = {"assigned": True, "status": "active", "plan_key": "custom", "entitlements": []}
    plan_read = MagicMock(side_effect=lambda *_: dict(plan))
    monkeypatch.setattr(pricing.usage, "get_plan", plan_read)
    single = MagicMock(return_value=RESULT)
    bulk = MagicMock(return_value={"total": 1, "decided": 1})
    monkeypatch.setattr(pricing.pricing_pipeline, "run_price_recommendation", single)
    monkeypatch.setattr(pricing.pricing_pipeline, "run_price_recommendations_for_all", bulk)
    app = FastAPI()
    app.include_router(pricing.router)
    app.dependency_overrides[get_tenant_context] = lambda: TenantContext(TENANT, ACTOR)
    register_exception_handlers(app)
    with TestClient(app) as client:
        yield client, plan, conn, single, bulk, connection, plan_read


def request(client, bulk=False, key=None):
    if bulk:
        return client.post("/pricing/recommend-all")
    return client.post("/pricing/recommend", params={"product_id": PRODUCT},
                       headers={"Idempotency-Key": key} if key else {})


@pytest.mark.parametrize("bulk", [False, True])
@pytest.mark.parametrize("plan_key", ["starter", "growth", "enterprise", "custom"])
@pytest.mark.parametrize("status", ["active", "trialing"])
def test_eligible_plans_need_no_pricing_or_market_entitlement(endpoint, bulk, plan_key, status):
    client, plan, conn, single, batch, connection, plan_read = endpoint
    plan.update(plan_key=plan_key, status=status)
    assert request(client, bulk).status_code == 200
    connection.assert_called_once_with(TENANT, ACTOR)
    plan_read.assert_called_once_with(conn, TENANT)
    (batch if bulk else single).assert_called_once()


@pytest.mark.parametrize("bulk", [False, True])
@pytest.mark.parametrize("status", ["none", "expired", "canceled", "past_due", "pending"])
def test_inactive_subscription_denies_before_execution_or_replay(endpoint, bulk, status):
    client, plan, conn, single, batch, *_ = endpoint
    plan["status"] = status
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (PRODUCT, RESULT)
    response = request(client, bulk, key="existing-result")
    assert response.status_code == 402
    assert response.json()["detail"]["reason"] == "SUBSCRIPTION_INACTIVE"
    assert response.json()["detail"]["feature_code"] is None
    single.assert_not_called()
    batch.assert_not_called()
    conn.cursor.assert_not_called()
    conn.rollback.assert_called_once()
    conn.close.assert_called_once()


@pytest.mark.parametrize("bulk", [False, True])
def test_unassigned_development_default_is_not_a_subscription(endpoint, bulk):
    client, plan, _, single, batch, *_ = endpoint
    plan.update(assigned=False, status="active")
    assert request(client, bulk).status_code == 402
    single.assert_not_called()
    batch.assert_not_called()


def test_replay_rechecks_current_subscription_and_never_recalculates(endpoint):
    client, plan, conn, single, batch, _, plan_read = endpoint
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (PRODUCT, RESULT)
    first = request(client, key="existing-result")
    assert first.status_code == 200 and first.json() == RESULT
    plan["status"] = "expired"
    assert request(client, key="existing-result").status_code == 402
    assert plan_read.call_count == 2
    single.assert_not_called()
    batch.assert_not_called()


def test_foreign_product_denial_remains_scoped_to_authenticated_tenant(endpoint):
    client, _, conn, single, *_ = endpoint
    single.side_effect = pricing.pricing_pipeline.ProductNotFoundError("foreign product")
    assert request(client).status_code == 404
    single.assert_called_once_with(conn, TENANT, str(UUID(PRODUCT)))
    conn.rollback.assert_called_once()


def test_real_local_calculation_does_not_reserve_credits_or_usage(endpoint, monkeypatch):
    from src.ai.billing import credits

    client, _, conn, *_ = endpoint
    pipeline = pricing.pricing_pipeline
    monkeypatch.setattr(pipeline, "run_price_recommendation", REAL_RECOMMEND)
    monkeypatch.setattr(pipeline.data_access, "load_own_product", lambda *_: {
        "current_price": 15.99, "cost": 8.0, "currency": "JOD",
    })
    monkeypatch.setattr(pipeline.data_access, "load_competitor_prices", lambda *_: [
        {"price_found": 15.0, "price_entry_id": "synthetic-price"},
    ])
    monkeypatch.setattr(pipeline.data_access, "load_cross_currency_competitor_prices", lambda *_: [])
    monkeypatch.setattr(pipeline, "_demand_context", lambda *_: None)
    evidence = MagicMock(return_value="synthetic-evidence")
    outcome = MagicMock(return_value="synthetic-outcome")
    monkeypatch.setattr(pipeline.evidence, "insert_evidence_record", evidence)
    monkeypatch.setattr(pipeline.evidence, "insert_recommendation_outcome", outcome)

    def unexpected_metering(*args, **kwargs):
        pytest.fail("Provider-free pricing must not reserve or consume Credits/usage")

    for module, names in [(credits, ("reserve", "settle")),
                          (pricing.usage, ("reserve", "record", "settle"))]:
        for name in names:
            monkeypatch.setattr(module, name, unexpected_metering)
    response = request(client)
    assert response.status_code == 200
    assert response.json()["action"] == "lower"
    assert response.json()["suggested_price"] == 15.0
    assert response.json()["data_basis"] == "LOCAL_MARKET"
    assert response.json()["confidence_score"] == 0.35
    evidence.assert_called_once()
    outcome.assert_called_once_with(conn, "synthetic-evidence", TENANT, "Lower price to 15.000 JOD")

"""Reuse real SQL fixtures; do not replace repositories or authorization."""
# ruff: noqa: F401, F811 -- imported pytest fixtures are registered here

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.billing.conftest import (
    billing_connections,
    no_external_network,
    owner_db,
    tenant,
    test_price,
)
from tests.billing.test_database import deliver
from tests.entitlements.conftest import (
    assigned,
    other_tenant,
    production_policy_defaults,
)


@pytest.fixture
def client():
    from src.ai.core.exceptions import register_exception_handlers
    from src.ai.routers import billing, reports

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(billing.router)
    app.include_router(reports.router)
    with TestClient(app) as result:
        yield result


@pytest.fixture
def higher_price(owner_db):
    key, price = (
        "test_review_" + uuid.uuid4().hex[:12],
        "price_test_" + uuid.uuid4().hex,
    )
    with owner_db.cursor() as cur:
        cur.execute(
            "INSERT INTO usage_plans(plan_key,display_name,display_name_ar,monthly_price,currency,trial_days,tier_level,self_serve,is_active) VALUES(%s,'Review fixture','Review fixture',85,'USD',0,2,TRUE,TRUE)",
            (key,),
        )
        cur.execute(
            "INSERT INTO billing_plan_prices(plan_key,period_code,interval_months,discount_percent,amount,currency,stripe_price_id) VALUES(%s,'monthly',1,0,85,'USD',%s)",
            (key, price),
        )
    yield key, price
    with owner_db.cursor() as cur:
        cur.execute("DELETE FROM tenant_plan_assignments WHERE plan_key=%s", (key,))
        cur.execute("DELETE FROM billing_subscriptions WHERE plan_key=%s", (key,))
        cur.execute("DELETE FROM billing_plan_prices WHERE plan_key=%s", (key,))
        cur.execute("DELETE FROM usage_plans WHERE plan_key=%s", (key,))

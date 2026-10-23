"""Reuse isolated billing database/auth fixtures, never the model test defaults."""
# ruff: noqa: F811 -- imported pytest fixtures are intentionally injected by name

import pytest

from tests.billing.conftest import (  # noqa: F401 -- pytest fixture reuse
    billing_connections,
    client,
    no_external_network,
    owner_db,
    tenant,
)


@pytest.fixture(autouse=True)
def production_policy_defaults(monkeypatch):
    monkeypatch.setenv("UNASSIGNED_PLAN_ACCESS", "none")
    monkeypatch.setenv("KEEL_TEST_DISABLE_METERING", "0")
    from src.ai.core import entitlements

    entitlements._cache.clear()
    yield
    entitlements._cache.clear()


@pytest.fixture
def assigned(owner_db, tenant):
    tid, uid = tenant
    with owner_db.cursor() as cur:
        cur.execute(
            "INSERT INTO tenant_plan_assignments(tenant_id,plan_key,status,current_period_start,current_period_end,source) VALUES(%s,'standard','active',date_trunc('month',CURRENT_DATE)::date,(date_trunc('month',CURRENT_DATE)+interval '1 month - 1 day')::date,'manual')",
            (tid,),
        )
    return tid, uid


@pytest.fixture
def other_tenant(owner_db):
    import uuid

    tid = str(uuid.uuid4())
    with owner_db.cursor() as cur:
        cur.execute(
            "INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,'Other tenant fixture','JO','JOD')",
            (tid,),
        )
        cur.execute(
            "INSERT INTO tenant_plan_assignments(tenant_id,plan_key,status) VALUES(%s,'pro','active')",
            (tid,),
        )
        cur.execute(
            "INSERT INTO tenant_usage_counters(tenant_id,feature_code,period_start,used) VALUES(%s,'monthly_reports',CURRENT_DATE,1)",
            (tid,),
        )
    yield tid
    with owner_db.cursor() as cur:
        cur.execute("DELETE FROM companies WHERE tenant_id=%s", (tid,))

"""Real HTTP-to-PostgreSQL verification for Platform Owner catalog mutations.

All values created here are synthetic and the test runner only targets a fresh
disposable database. No Stripe/provider operations are performed.
"""
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ai.billing import custom_offers
from src.ai.core.security import TenantContext
from src.ai.routers import platform


def test_owner_catalog_http_mutations_persist_rate_binding_and_audit(
    owner_db, billing_connections, platform_owner_context
):
    tenant_id, user_id = platform_owner_context
    owner_conn = billing_connections(tenant_id, user_id)
    policy = custom_offers.pricing_admin_command(owner_conn, "policy_create", {
        "target_gross_margin": "0.25", "enforce_vendor_cost_ratio_floor": False,
        "max_vendor_cost_revenue_ratio": None, "fixed_platform_fee_usd": "0",
        "upward_rounding_increment_usd": "0", "monthly_shared_infrastructure_cost_usd": "0",
        "active_paying_tenant_count": 1,
        "approval_evidence": "SYNTHETIC_TEST_ONLY: never a commercial policy",
    })
    owner_conn.commit()
    owner_conn.close()

    app = FastAPI()
    app.include_router(platform.router)
    app.dependency_overrides[platform.get_tenant_context] = lambda: TenantContext(tenant_id, user_id)
    with owner_db.cursor() as cur:
        cur.execute("SELECT feature_code,display_name,display_name_ar,description,description_ar FROM public.usage_features ORDER BY feature_code LIMIT 1")
        feature = cur.fetchone()
    assert feature
    feature_code, *old_metadata = feature
    with owner_db.cursor() as cur:
        cur.execute("SELECT count(*) FROM public.keel_platform_audit WHERE action='feature_catalog_metadata_update' AND subject=%s", (feature_code,))
        audit_before = cur.fetchone()[0]

    body = {
        "policy_version_id": policy["policy_version_id"], "feature_code": feature_code,
        "provider": "synthetic-infra-" + uuid4().hex[:12], "operation": "synthetic-storage",
        "unit": "GB-month", "unit_cost_usd": "0.0002",
        "source": "SYNTHETIC_TEST_ONLY: generated fixture", "verified_at": "2026-10-24",
        "effective_from": "2026-10-25T00:00:00Z", "usage_basis": "estimated_usage",
        "units_per_feature_unit": "0.001", "operational_multiplier": "1.1",
        "variability_reserve": "1.2", "required_for_price": True,
        "usage_assumption": {"fixture": "test-only"},
    }
    try:
        with TestClient(app) as client:
            catalog = client.get("/platform/billing/feature-catalog")
            assert catalog.status_code == 200
            assert any(row["feature_code"] == feature_code for row in catalog.json()["features"])

            saved = client.post("/platform/billing/custom-plan-pricing/infrastructure-rates", json=body)
            assert saved.status_code == 201, saved.text
            rate_id = saved.json()["cost_rate"]["cost_rate_id"]
            binding_id = saved.json()["binding"]["binding_id"]

            listed = client.get("/platform/billing/custom-plan-pricing/infrastructure-rates")
            assert listed.status_code == 200
            assert any(row["id"] == rate_id and row["bindingId"] == binding_id for row in listed.json()["items"])

            new_name = "Synthetic catalog test"
            updated = client.patch(f"/platform/billing/feature-catalog/{feature_code}", json={
                "name": new_name, "name_ar": "اسم اختبار اصطناعي",
                "description": "SYNTHETIC_TEST_ONLY", "description_ar": "بيانات اختبار اصطناعية",
                "reason": "SYNTHETIC_TEST_ONLY: verify owner metadata audit",
            })
            assert updated.status_code == 200, updated.text
            assert updated.json()["display_name"] == new_name

        with owner_db.cursor() as cur:
            cur.execute("SELECT budget_kind,unit,unit_cost_usd FROM public.billing_custom_cost_rates WHERE cost_rate_id=%s", (rate_id,))
            assert cur.fetchone() == ("infrastructure", "GB-month", Decimal("0.0002"))
            cur.execute("SELECT cost_category,budget_kind,usage_basis FROM public.billing_custom_cost_bindings WHERE binding_id=%s", (binding_id,))
            assert cur.fetchone() == ("infrastructure", "infrastructure", "estimated_usage")
            cur.execute("SELECT count(*) FROM public.entitlement_audit_log WHERE action='custom_pricing_rate_created' AND new_value->>'cost_rate_id'=%s", (rate_id,))
            assert cur.fetchone()[0] == 1
            cur.execute("SELECT count(*) FROM public.keel_platform_audit WHERE action='feature_catalog_metadata_update' AND subject=%s", (feature_code,))
            assert cur.fetchone()[0] == audit_before + 1
    finally:
        # Restore presentation metadata only; synthetic pricing objects remain
        # in the disposable test DB so their immutable audit evidence is intact.
        with owner_db.cursor() as cur:
            cur.execute("UPDATE public.usage_features SET display_name=%s,display_name_ar=%s,description=%s,description_ar=%s WHERE feature_code=%s", (*old_metadata, feature_code))
        owner_db.commit()

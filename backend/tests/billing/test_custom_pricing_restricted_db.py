"""Real calculator, restricted owner connection and immutable SQL evidence."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ai.billing import custom_offers
from src.ai.core.security import TenantContext
from src.ai.routers import platform
from src.ai.billing import admin


def test_paid_quote_allowances_are_closed_without_changing_quote_omission_semantics():
    selected = {"connected_data_sources": 10}
    actual = admin.closed_quote_limits(selected)
    assert actual["connected_data_sources"] == 10
    assert actual["data_credits"] == actual["ai_credits"] == 0
    assert all(value == 0 for code, value in actual.items() if code != "connected_data_sources")
    assert selected == {"connected_data_sources": 10}
    with pytest.raises(admin.AdminError):
        admin.closed_quote_limits({"connected_data_sources": True})


def test_verified_quote_recovery_only_fills_missing_limits_and_preserves_newer_contract(owner_db, tenant):
    tenant_id, _ = tenant
    ref = "custom-quote:synthetic-closed-allowance-test"
    admin.set_custom_contract(owner_db, tenant_id=tenant_id, contract_ref=ref,
        approved_by="synthetic-owner", reason="SYNTHETIC_TEST_ONLY",
        limits={"connected_data_sources": 10, "data_credits": 7}, included_features=[])
    admin.fill_missing_quote_limits(owner_db, tenant_id=tenant_id, contract_ref=ref,
        selected={"connected_data_sources": 10}, approved_by="synthetic-owner", reason="SYNTHETIC_TEST_ONLY replay")
    with owner_db.cursor() as cur:
        cur.execute("SELECT feature_code,limit_value FROM tenant_entitlement_overrides WHERE tenant_id=%s", (tenant_id,))
        actual = dict(cur.fetchall())
        assert actual["data_credits"] == 7  # explicit administrative adjustment remains
        assert actual["ai_credits"] == actual["tracked_products"] == 0
        assert actual["connected_data_sources"] == 10
        cur.execute("SELECT count(*) FROM entitlement_audit_log WHERE tenant_id=%s", (tenant_id,))
        count = cur.fetchone()[0]
    admin.fill_missing_quote_limits(owner_db, tenant_id=tenant_id, contract_ref=ref,
        selected={"connected_data_sources": 10}, approved_by="synthetic-owner", reason="SYNTHETIC_TEST_ONLY duplicate")
    with owner_db.cursor() as cur:
        cur.execute("SELECT count(*) FROM entitlement_audit_log WHERE tenant_id=%s", (tenant_id,))
        assert cur.fetchone()[0] == count
        cur.execute("DELETE FROM tenant_entitlement_overrides WHERE tenant_id=%s AND feature_code='ai_credits'", (tenant_id,))
        cur.execute("UPDATE tenant_custom_contracts SET contract_ref='newer-owner-contract' WHERE tenant_id=%s", (tenant_id,))
    admin.fill_missing_quote_limits(owner_db, tenant_id=tenant_id, contract_ref=ref,
        selected={"connected_data_sources": 10}, approved_by="synthetic-owner", reason="SYNTHETIC_TEST_ONLY late event")
    with owner_db.cursor() as cur:
        cur.execute("SELECT 1 FROM tenant_entitlement_overrides WHERE tenant_id=%s AND feature_code='ai_credits'", (tenant_id,))
        assert cur.fetchone() is None


def test_restricted_owner_calculator_prices_bound_rate_without_private_table_grant(
    owner_db, billing_connections, platform_owner_context, tenant, monkeypatch
):
    platform_tenant, platform_user = platform_owner_context
    tenant_id, user_id = tenant
    conn = billing_connections(platform_tenant, platform_user)
    now = datetime.now(timezone.utc)
    evidence = "SYNTHETIC_TEST_ONLY: isolated calculator regression"
    try:
        policy = custom_offers.pricing_admin_command(conn, "policy_create", {
            "target_gross_margin": "0.25", "enforce_vendor_cost_ratio_floor": False,
            "fixed_platform_fee_usd": "0", "upward_rounding_increment_usd": "0",
            "monthly_shared_infrastructure_cost_usd": "0", "approval_evidence": evidence,
        })
        rate = custom_offers.pricing_admin_command(conn, "rate_create", {
            "budget_kind": "data", "provider": "synthetic-" + uuid4().hex,
            "operation": "source-month", "unit": "request", "unit_cost_usd": "1",
            "source": evidence, "verification_evidence": evidence,
            "verified_at": now.date().isoformat(),
            "effective_from": (now-timedelta(minutes=1)).isoformat(),
        })
        custom_offers.pricing_admin_command(conn, "binding_create", {
            "policy_version_id": policy["policy_version_id"], "cost_rate_id": rate["cost_rate_id"],
            "feature_code": "connected_data_sources", "cost_category": "vendor",
            "usage_basis": "limit_value", "units_per_feature_unit": "1",
            "operational_multiplier": "1", "variability_reserve": "1",
            "effective_from": now.isoformat(), "source": evidence,
        })
        custom_offers.pricing_admin_command(conn, "policy_activate", {
            **policy, "approval_evidence": evidence,
        })
        quote = custom_offers.create_draft(conn, tenant_id=tenant_id, customer_user_id=user_id,
            idempotency_key=str(uuid4()), configuration={"enabledFeatures": []},
            feature_quantities={"connected_data_sources": 10}, commercial_terms={},
            economic_inputs={}, fx_evidence={})
        custom_offers.transition(conn, "submit", tenant_id=None, quote_id=str(quote["quote_id"]),
            expected_revision=1, idempotency_key=str(uuid4()))
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT has_table_privilege(current_user,'public.provider_cost_schedules','SELECT')")
            assert cur.fetchone()[0] is False
    finally:
        conn.close()
    app = FastAPI()
    app.include_router(platform.router)
    app.dependency_overrides[platform.get_tenant_context] = lambda: TenantContext(platform_tenant, platform_user)
    monkeypatch.setattr(platform.db, "app_role_connection", billing_connections)
    with TestClient(app) as client:
        calculated = client.post(f"/platform/billing/custom-quotes/{quote['quote_id']}/calculate")
        assert calculated.status_code == 200, calculated.text
        assert calculated.json()["monthlyPrice"] == "13.33"
    with owner_db.cursor() as cur:
        cur.execute("SELECT pricing_snapshot FROM billing_custom_quote_revisions WHERE revision_id=%s", (quote["revision_id"],))
        snapshot = cur.fetchone()[0]
        assert snapshot["calculation"]["recommendedPrice"] == "13.33"
        assert snapshot["rates"][0]["providerScheduleId"] == rate["cost_rate_id"]
    customer = billing_connections(tenant_id, user_id)
    try:
        with customer.cursor() as cur, pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute("SELECT * FROM billing_custom_pricing_rate_evidence(%s,%s::text[],now())",
                        (policy["policy_version_id"], ["connected_data_sources"]))
        customer.rollback()
    finally:
        customer.close()

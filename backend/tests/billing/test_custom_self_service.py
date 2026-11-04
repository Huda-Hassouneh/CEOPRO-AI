"""Legacy decision vectors plus restricted native frozen-quote transitions."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import psycopg2
from psycopg2.extras import Json
import pytest

from src.ai.billing import self_service, service, custom_offers, store, stripe_api
from .test_reconciliation_roles import restricted_runtime, send  # noqa: F401 — native fixtures
from .test_database import live_subscription


def inputs():
    now = datetime.now(timezone.utc)
    return {"policy": None, "bindings": [{
        "binding_id": str(uuid4()), "feature_code": "connected_data_sources", "rate_id": str(uuid4()),
        "unit_cost_usd": "1", "cost_is_final": True, "verified_at": now.date().isoformat(),
        "updated_at": now.isoformat(), "provider": "synthetic", "operation": "source-month", "unit": "request",
        "usage_basis": "limit_value", "units_per_feature_unit": "1", "operational_multiplier": "1",
        "variability_reserve": "1", "cost_category": "vendor", "usage_assumption": {}, "rate_source": "synthetic test",
    }]}


def config(q=10):
    return {"limits": {"connected_data_sources": q}, "enabledFeatures": [], "refreshFrequency": None,
            "billingPeriod": "monthly"}


def test_legacy_jod_fallback_price_and_payment_vector():
    result = self_service.calculate(config(), inputs())
    # USD 10 -> JOD 7.09 / .65 + fee25 -> ceil to JOD36 -> USD50.78.
    assert result["monthlyPrice"] == result["price"] == "36.00"
    assert result["paymentAmount"] == "50.78"
    assert result["reviewRequired"] is False and result["checkoutAllowed"] is True
    assert result["pricingSnapshot"]["fx"]["version"] == "legacy-fallback-v1"


@pytest.mark.parametrize("quantity,policy,unverified,reason", [
    (500001, {}, False, "QUOTA_ABOVE_AUTOMATIC_LIMIT:connected_data_sources"),
    (10, {"maxAutomaticMonthlyPrice": "35"}, False, "PRICE_ABOVE_AUTOMATIC_LIMIT"),
    (10, {}, True, "UNVERIFIED_VENDOR_RATE"),
])
def test_review_price_remains_visible_and_checkout_is_blocked(quantity, policy, unverified, reason):
    data = inputs()
    data["policy"] = {"policy_version_id": str(uuid4()), "self_service_policy": policy}
    if unverified:
        data["bindings"][0]["verified_at"] = None
    result = self_service.calculate(config(quantity), data)
    assert result["pricingAvailable"] and Decimal(result["price"]) > 0
    assert result["reviewRequired"] and not result["checkoutAllowed"]
    assert reason in result["reasons"]


def test_override_precedence_equality_and_step_validation():
    data = inputs()
    data["policy"] = {"policy_version_id": str(uuid4()), "self_service_policy": {
        "targetGrossMargin": "0", "fixedPlatformFee": "0", "roundingIncrement": "0",
        "maxAutomaticMonthlyPrice": "7.09", "featureLimits": {"connected_data_sources": {"max": 10, "step": 2}}}}
    result = self_service.calculate(config(), data)
    assert result["price"] == "7.09" and not result["reviewRequired"]
    with pytest.raises(custom_offers.CustomOfferError):
        self_service.calculate(config(9), data)


def test_three_month_discount_precedes_frozen_usd_conversion():
    configuration = config()
    configuration["billingPeriod"] = "three-months"
    result = self_service.calculate(configuration, inputs())
    assert result["price"] == "97.20" and result["paymentAmount"] == "137.09"
    assert self_service.checkout_terms({"currency": "JOD", "amount": "97.20", "paymentCurrency": "USD",
        "paymentAmountUsd": "137.09", "billingPeriodMonths": 3, "periodCode": "three-months",
        "fx": result["pricingSnapshot"]["fx"]}) == (Decimal("137.09"), 3, "three-months")


def test_forged_payment_amount_rejected():
    with pytest.raises(ValueError):
        self_service.checkout_terms({"currency": "JOD", "amount": "36", "paymentCurrency": "USD",
            "paymentAmountUsd": "36", "fx": {"rate": ".709", "sourceCurrency": "USD", "targetCurrency": "JOD"}})


def test_missing_cost_provenance_cannot_be_automatically_approved():
    data = inputs()
    data["bindings"][0]["rate_source"] = ''
    result = self_service.calculate(config(), data)
    assert result["reviewRequired"] and result["reasons"] == ["UNVERIFIED_VENDOR_RATE"]


def test_v2_checkout_amount_uses_frozen_snapshot(monkeypatch, memory_checkout_reservations):
    from unittest.mock import MagicMock
    captured = {}
    snapshot = self_service.calculate(config(), inputs())["pricingSnapshot"]
    terms = {"currency": "JOD", "amount": "36.00", "monthlyPrice": "36.00", "paymentCurrency": "USD",
             "paymentAmountUsd": "50.78", "billingPeriodMonths": 1, "periodCode": "monthly", "fx": snapshot["fx"]}
    monkeypatch.setattr(service.config, "payments_enabled", lambda: True)
    monkeypatch.setattr(service.config, "app_base_url", lambda: "https://local.test")
    monkeypatch.setattr(store, "current_subscription", lambda *_: None)
    monkeypatch.setattr(service, "_ensure_customer", lambda *_: "cus_synthetic")
    monkeypatch.setattr(custom_offers, "custom_checkout_prepare", lambda *a, **k: {
        "attempt_id": str(uuid4()), "revision_id": "revision", "commercial_terms": terms})
    monkeypatch.setattr(custom_offers, "record_custom_checkout_session", lambda *a, **k: None)
    def create(params, **kwargs):
        captured.update(params)
        return {"id": "cs_test_synthetic", "url": "https://checkout.stripe.test"}
    monkeypatch.setattr(stripe_api, "create_checkout_session", create)
    service.create_custom_quote_checkout(MagicMock(), object(), "tenant", "test@example.test", "Test", "quote", "key")
    assert captured["line_items"][0]["price_data"]["unit_amount"] == 5078
    with pytest.raises(service.BillingError) as err:
        service.create_custom_quote_checkout(object(), object(), "tenant", "test@example.test", "Test", "different-quote", "key")
    assert err.value.code == "checkout_pending"


def test_native_setup_capability_is_not_callable_by_app(owner_db, tenant, billing_connections):
    tid, uid = tenant
    conn = billing_connections(tid, uid)
    try:
        with pytest.raises(psycopg2.errors.InsufficientPrivilege), conn.cursor() as cur:
            cur.execute("SELECT billing_custom_self_service('inputs','{}')")
        conn.rollback()
    finally:
        conn.close()


def test_native_freeze_and_cross_tenant_reference(owner_db, tenant, platform_owner_context, billing_connections):
    from src.infrastructure.db_pool import PooledTenantConnection
    from scripts.billing_verification import validate_test_environment
    import os
    tid, uid = tenant
    raw = psycopg2.connect(validate_test_environment(dict(os.environ), database=True))
    raw.autocommit = True
    with raw.cursor() as cur:
        cur.execute("SET ROLE ceopro_billing_setup")
    raw.autocommit = False
    class Pool:
        def putconn(self, connection, discard=False):
            connection.close()
    conn = PooledTenantConnection(Pool(), raw, tid, uid)
    try:
        data = inputs()
        rate = data["bindings"][0]
        with owner_db.cursor() as cur:
            cur.execute("""INSERT INTO billing_custom_cost_rates(cost_rate_id,budget_kind,provider,operation,unit,unit_cost_usd,
              source,verified_at,effective_from,verified_by,verification_evidence)
              VALUES(%s,'data','synthetic','source-month','request',1,'synthetic test',CURRENT_DATE,now()-interval '1 day','test','test')""", (rate["rate_id"],))
            cur.execute("SELECT unit_cost_usd::text FROM billing_custom_cost_rates WHERE cost_rate_id=%s", (rate["rate_id"],))
            rate["unit_cost_usd"] = cur.fetchone()[0]
        snapshot = self_service.calculate(config(), data)["pricingSnapshot"]
        frozen = self_service.command(conn, "freeze", {"snapshot": snapshot, "idempotency_key": str(uuid4())})
        conn.commit()
        assert custom_offers.quote_list(owner_db, tid) == []  # Price edits are not review requests.
        # No paid assignment is created by preview or customer confirmation.
        with owner_db.cursor() as cur:
            cur.execute("SELECT count(*) FROM tenant_plan_assignments WHERE tenant_id=%s", (tid,))
            assert cur.fetchone()[0] == 0
        with pytest.raises(custom_offers.CustomOfferError) as err:
            self_service.command(conn, "checkout", {"preview_id": str(uuid4())})
        assert err.value.status == 404
        conn.rollback()
        assert frozen["quote_id"]
        promoted = self_service.command(conn, "checkout", {"preview_id": frozen["quote_id"]})
        conn.commit()
        assert len(custom_offers.quote_list(owner_db, tid)) == 1
        assert self_service.command(conn, "checkout", {"preview_id": frozen["quote_id"]}) == promoted
        conn.commit()
        with owner_db.cursor() as cur:
            cur.execute("SELECT count(*) FROM tenant_plan_assignments WHERE tenant_id=%s", (tid,))
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT state,commercial_terms FROM billing_custom_quote_revisions WHERE quote_id=%s", (frozen["quote_id"],))
            state, terms = cur.fetchone()
            assert state == "accepted" and terms["paymentAmountUsd"] == "50.78" and terms["currency"] == "JOD"
        # A priced review request retains frozen JOD/FX evidence through the
        # established human approval and separate customer acceptance workflow.
        review_snapshot = self_service.calculate(config(3000), data)["pricingSnapshot"]
        assert review_snapshot["reviewDecision"]["required"]
        review = self_service.command(conn, "freeze", {"snapshot": review_snapshot, "idempotency_key": str(uuid4())})
        conn.commit()
        with pytest.raises(custom_offers.CustomOfferError):
            self_service.command(conn, "checkout", {"preview_id": review["quote_id"]})
        conn.rollback()
        self_service.command(conn, "review", {"preview_id": review["quote_id"]})
        conn.commit()
        operator = billing_connections(*platform_owner_context)
        customer = billing_connections(tid, uid)
        try:
            custom_offers.transition(operator, "approve", tenant_id=None, quote_id=review["quote_id"],
                expected_revision=1, idempotency_key=str(uuid4()), approval_reference="SYNTHETIC review approval")
            operator.commit()
            with owner_db.cursor() as cur:
                cur.execute("SELECT count(*) FROM tenant_plan_assignments WHERE tenant_id=%s", (tid,))
                assert cur.fetchone()[0] == 0
            custom_offers.transition(customer, "accept", tenant_id=tid, quote_id=review["quote_id"],
                expected_revision=1, idempotency_key=str(uuid4()))
            customer.commit()
            accepted = custom_offers.quote_detail(customer, review["quote_id"])
            assert accepted["commercial_terms"]["amount"] == review_snapshot["commercial"]["amount"]
            assert accepted["commercial_terms"]["paymentAmountUsd"] == review_snapshot["payment"]["amount"]
            assert accepted["commercial_terms"]["fx"] == review_snapshot["fx"]
            with owner_db.cursor() as cur:
                cur.execute("SELECT pricing_snapshot FROM billing_custom_quote_revisions WHERE quote_id=%s", (review["quote_id"],))
                assert cur.fetchone()[0] == review_snapshot
            with owner_db.cursor() as cur:
                cur.execute("SELECT count(*) FROM tenant_plan_assignments WHERE tenant_id=%s", (tid,))
                assert cur.fetchone()[0] == 0
        finally:
            operator.close()
            customer.close()
    finally:
        conn.close()


def test_native_automatic_checkout_and_signed_paid_activation(client, send, owner_db, tenant, monkeypatch):
    """Actual restricted sockets and signatures; only Stripe transport is doubled."""
    from contextlib import closing
    from src.ai import db
    from src.ai.core.security import TenantContext, get_tenant_context
    from src.ai.core import usage
    import time
    tid, uid = tenant
    data = inputs()
    with owner_db.cursor() as cur:
        rate = data["bindings"][0]
        cur.execute("""INSERT INTO billing_custom_cost_rates(cost_rate_id,budget_kind,provider,operation,unit,unit_cost_usd,
          source,verified_at,effective_from,verified_by,verification_evidence)
          VALUES(%s,'data','synthetic','source-month','request',1,'synthetic test',CURRENT_DATE,now()-interval '1 day','test','test')""", (rate["rate_id"],))
        cur.execute("SELECT unit_cost_usd::text FROM billing_custom_cost_rates WHERE cost_rate_id=%s", (rate["rate_id"],))
        rate["unit_cost_usd"] = cur.fetchone()[0]
    snapshot = self_service.calculate(config(), data)["pricingSnapshot"]
    with closing(db.billing_setup_connection(tid, uid)) as setup:
        frozen = self_service.command(setup, "freeze", {"snapshot": snapshot, "idempotency_key": str(uuid4())})
        setup.commit()
    client.app.dependency_overrides[get_tenant_context] = lambda: TenantContext(tid, uid)
    monkeypatch.setattr(service.config, "payments_enabled", lambda: True)
    monkeypatch.setattr(service.config, "app_base_url", lambda: "https://local.test")
    customer_id, session_id = "cus_" + uuid4().hex, "cs_test_" + uuid4().hex
    monkeypatch.setattr(stripe_api, "create_customer", lambda *a, **k: {"id": customer_id,"metadata":{"tenant_id":a[2]}})
    captured = {}
    provider_requests = []
    def create(params, **kwargs):
        captured.update(params)
        provider_requests.append((params, kwargs))
        if len(provider_requests) == 1:
            raise TimeoutError("SYNTHETIC uncertain provider response")
        return {"id": session_id, "url": "https://checkout.stripe.test", "status": "open"}
    monkeypatch.setattr(stripe_api, "create_checkout_session", create)
    checkout_request = {"preview_id": frozen["quote_id"], "idempotency_key": str(uuid4())}
    failed = client.post('/billing/custom-offers/checkout', json=checkout_request)
    assert failed.status_code == 502 and failed.json()['detail']['reason'] == 'provider_error'
    with owner_db.cursor() as cur:
        cur.execute("SELECT attempt_id,provider_params FROM billing_checkout_attempts WHERE tenant_id=%s", (tid,))
        shared_before = cur.fetchall()
        cur.execute("SELECT attempt_id FROM billing_custom_quote_checkout_attempts WHERE tenant_id=%s", (tid,))
        quote_before = cur.fetchall()
        assert len(shared_before) == len(quote_before) == 1
        cur.execute("SELECT count(*) FROM tenant_plan_assignments WHERE tenant_id=%s", (tid,))
        assert cur.fetchone()[0] == 0
    response = client.post('/billing/custom-offers/checkout', json=checkout_request)
    assert response.status_code == 200, response.text
    assert len(provider_requests) == 2 and provider_requests[0] == provider_requests[1]
    assert response.json()['attempt_id'] == str(quote_before[0][0])
    with owner_db.cursor() as cur:
        cur.execute("SELECT attempt_id,provider_params FROM billing_checkout_attempts WHERE tenant_id=%s", (tid,))
        assert cur.fetchall() == shared_before
    assert captured["line_items"][0]["price_data"]["unit_amount"] == 5078
    assert store.current_subscription(owner_db, tid) is None
    live = live_subscription(tid, "price_custom_offline")
    live.update(id="sub_" + uuid4().hex, customer=customer_id)
    live["metadata"].update(captured["metadata"])
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda _: live)
    completed = {"id": session_id, "mode": "subscription", "subscription": live["id"], "customer": customer_id,
                 "metadata": captured["metadata"], "client_reference_id": captured["client_reference_id"]}
    assert send("checkout.session.completed", completed).status_code == 200
    assert store.current_subscription(owner_db, tid) is None
    with owner_db.cursor() as cur:
        cur.execute("SELECT count(*) FROM tenant_plan_assignments WHERE tenant_id=%s", (tid,))
        assert cur.fetchone()[0] == 0
    invoice = dict(id="in_" + uuid4().hex, customer=customer_id, subscription=live["id"], currency="usd",
        amount_paid=5078, status="paid", paid=True, billing_reason="subscription_create", status_transitions={"paid_at": int(time.time())})
    monkeypatch.setattr(stripe_api, "retrieve_invoice", lambda _: invoice)
    invoice["amount_paid"] = 5077
    assert send("invoice.paid", invoice).status_code == 500
    assert store.current_subscription(owner_db, tid) is None
    invoice["amount_paid"] = 5078
    paid = send("invoice.paid", invoice)
    assert paid.status_code == 200, paid.text
    assert send("invoice.paid", invoice).status_code == 200
    with closing(db.app_role_connection(tid, uid)) as conn:
        plan = usage.get_plan(conn, tid)
        assert plan["status"] == "active" and plan["features"]["connected_data_sources"]["limit"] == 10
        assert plan["features"]["data_credits"]["limit"] == plan["features"]["ai_credits"]["limit"] == 0
        assert store.subscription_price_snapshot(conn, tid)["amount"] == 50.78
    with owner_db.cursor() as cur:
        cur.execute("SELECT monthly_price,currency FROM tenant_custom_contracts WHERE tenant_id=%s", (tid,))
        assert cur.fetchone() == (Decimal("36.00"), "JOD")


@pytest.mark.parametrize('status', ['trialing', 'active', 'past_due', 'pending', 'payment_failed', 'paused'])
def test_automatic_checkout_refuses_every_current_subscription_before_setup(client, monkeypatch, status):
    from unittest.mock import MagicMock
    from src.ai.core.security import TenantContext
    from src.ai.routers import billing
    client.app.dependency_overrides[billing.get_tenant_context] = lambda: TenantContext('tenant', 'user')
    monkeypatch.setattr(billing.db, 'app_role_connection', lambda *_: MagicMock())
    monkeypatch.setattr(billing, '_require_billing_role', lambda *_: None)
    monkeypatch.setattr(service.config, 'payments_enabled', lambda: True)
    monkeypatch.setattr(store, 'current_subscription', lambda *_: {'status':status,'cancel_at_period_end':True})
    monkeypatch.setattr(billing.db, 'billing_setup_connection', lambda *_: pytest.fail('overlap reached setup'))
    response = client.post('/billing/custom-offers/checkout', json={'preview_id':str(uuid4()),'idempotency_key':'key'})
    assert response.status_code == 409 and response.json()['detail']['reason'] == 'subscription_exists'

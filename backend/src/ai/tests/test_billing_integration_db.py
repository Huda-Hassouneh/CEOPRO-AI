"""
Billing against a real Postgres: trials, checkout, the signed Stripe webhook
(signature, duplicates, stale events), plan sync and tenant isolation.
Stripe itself is replaced by fakes of src.ai.billing.stripe_api; the webhook
signature is computed exactly as Stripe does (HMAC-SHA256 of "t.payload").
"""
import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import date, datetime, timedelta, timezone

import psycopg2
import pytest

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")

from src.ai.billing import config, service, store, stripe_api, webhooks  # noqa: E402
from src.ai.core import usage  # noqa: E402

WEBHOOK_SECRET = "whsec_test_apex"


@pytest.fixture
def sys_conn():
    conn = psycopg2.connect(DATABASE_URL)
    yield conn
    conn.rollback()
    conn.close()


def _company(conn) -> str:
    tenant_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, %s, 'JO', 'JOD');",
            (tenant_id, f"Billing Test {tenant_id[:8]}"),
        )
    conn.commit()
    return tenant_id


def _price_id(conn, plan_key, period, stripe_id):
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE billing_plan_prices SET stripe_price_id = %s WHERE plan_key = %s AND period_code = %s AND retired_at IS NULL;",
            (stripe_id, plan_key, period),
        )
    conn.commit()


@pytest.fixture
def stripe_prices(sys_conn):
    ids = {
        ("starter", "monthly"): f"price_std_m_{uuid.uuid4().hex[:6]}",
        ("growth", "monthly"): f"price_pro_m_{uuid.uuid4().hex[:6]}",
        ("growth", "six-months"): f"price_pro_6_{uuid.uuid4().hex[:6]}",
    }
    with sys_conn.cursor() as cursor:
        cursor.execute("SELECT plan_key, period_code, stripe_price_id FROM billing_plan_prices WHERE retired_at IS NULL;")
        original = cursor.fetchall()
    for (plan, period), sid in ids.items():
        _price_id(sys_conn, plan, period, sid)
    yield ids
    for plan, period, sid in original:
        _price_id(sys_conn, plan, period, sid)


def _stripe_sub(sub_id, customer, price_id, status="active", cancel=False, trial_end=None):
    now = int(time.time())
    return {
        "id": sub_id, "object": "subscription", "customer": customer, "status": status,
        "cancel_at_period_end": cancel, "canceled_at": None, "trial_end": trial_end, "schedule": None,
        "metadata": {},
        "items": {"data": [{"id": "si_1", "price": {"id": price_id}, "current_period_start": now, "current_period_end": now + 30 * 86400}]},
    }


def test_the_catalog_lists_self_serve_plans_with_prices_and_limits(sys_conn):
    plans = {p["plan_key"]: p for p in store.catalog(sys_conn)}
    # Radar's agreed plan terms (docs/PLAN_LIMITS_FEASIBILITY.md).
    assert {k: (p["name"]["en"], p["monthly_price"], p["trial_days"]) for k, p in plans.items() if p["self_serve"]} == {
        "starter": ("Standard", 55.0, 14), "growth": ("Plus", 140.0, 14), "enterprise": ("Pro", 350.0, 7)}
    # A trial gets a bounded tenth of a paid month's credits, never the whole month.
    assert {k: plans[k]["trial_limits"] for k in ("starter", "growth", "enterprise")} == {
        "starter": {"data_credits": 43, "ai_credits": 43}, "growth": {"data_credits": 111, "ai_credits": 111},
        "enterprise": {"data_credits": 278, "ai_credits": 278}}
    assert {p["period_code"] for p in plans["growth"]["prices"]} == {"monthly", "three-months", "six-months"}
    amounts = {k: {p["period_code"]: p["amount"] for p in plans[k]["prices"]} for k in ("starter", "growth", "enterprise")}
    assert amounts == {"starter": {"monthly": 55.0, "three-months": 148.5, "six-months": 264.0},
                       "growth": {"monthly": 140.0, "three-months": 378.0, "six-months": 672.0},
                       "enterprise": {"monthly": 350.0, "three-months": 945.0, "six-months": 1680.0}}
    assert plans["custom"]["self_serve"] is False and plans["custom"]["prices"] == []
    assert "standard" not in plans and "pro" not in plans, "retired packages are no longer sold"
    # KEEL's subscription terms (docs/SUBSCRIPTIONS_AND_CREDITS.md): Standard / Plus / Pro.
    # products, reports/month, seats, competitors (None: budget-based), Data and AI Credits,
    # reviews/month, AI token safety cap, sources, storage MB, uploads KB/month, images
    agreed = {
        "starter": (100, 5, 5, None, 436, 436, 5000, 100000, 1, 1024, 51200, 20),
        "growth": (250, 20, 20, None, 1111, 1111, 25000, 500000, 5, 10240, 512000, 100),
        "enterprise": (500, 60, 50, None, 2780, 2780, 100000, 2000000, 20, 51200, 2097152, 150),
    }
    features = ("tracked_products", "monthly_reports", "team_seats", "tracked_competitors", "data_credits", "ai_credits",
                "sentiment_analysis", "rag_assistant", "connected_data_sources", "document_storage_mb",
                "document_extraction", "marketing_image_generation")
    for plan_key, values in agreed.items():
        assert tuple(plans[plan_key]["limits"][f] for f in features) == values, plan_key
        # Every plan includes the core intelligence; plans differ by capacity.
        assert {"market_intelligence", "demand_prediction", "competitor_management"} <= set(plans[plan_key]["entitlements"])


def test_retired_stripe_price_remains_resolvable_but_is_not_sold(sys_conn, stripe_prices):
    historical_price = stripe_prices[("growth", "monthly")]
    with sys_conn.cursor() as cursor:
        cursor.execute(
            "UPDATE billing_plan_prices SET retired_at = CURRENT_TIMESTAMP "
            "WHERE plan_key = 'growth' AND period_code = 'monthly' AND stripe_price_id = %s;",
            (historical_price,),
        )
    sys_conn.commit()
    try:
        assert store.resolve_price(sys_conn, historical_price) == ("growth", "monthly")
        current = {
            price["period_code"]
            for plan in store.catalog(sys_conn)
            if plan["plan_key"] == "growth"
            for price in plan["prices"]
        }
        assert "monthly" not in current
    finally:
        with sys_conn.cursor() as cursor:
            cursor.execute(
                "UPDATE billing_plan_prices SET retired_at = NULL "
                "WHERE plan_key = 'growth' AND period_code = 'monthly' AND stripe_price_id = %s;",
                (historical_price,),
            )
        sys_conn.commit()


def test_a_company_gets_the_free_trial_once(sys_conn):
    tenant = _company(sys_conn)
    first = store.start_trial(sys_conn, tenant)
    sys_conn.commit()
    assert first and first["plan_key"] == "growth"
    assert store.start_trial(sys_conn, tenant) is None
    plan = usage.get_plan(sys_conn, tenant)
    assert plan["status"] == "trialing" and plan["plan_key"] == "growth" and plan["source"] == "trial"


def test_an_ended_trial_no_longer_grants_access(sys_conn):
    tenant = _company(sys_conn)
    past = datetime.now(timezone.utc) - timedelta(days=30)
    store.start_trial(sys_conn, tenant, now=past)
    sys_conn.commit()
    plan = usage.get_plan(sys_conn, tenant)
    assert plan["status"] == "expired"
    with pytest.raises(usage.PlanLimitReached) as err:
        usage.reserve(sys_conn, tenant, usage.RAG_ASSISTANT)
    assert err.value.reason == "SUBSCRIPTION_INACTIVE"


def test_payment_actions_say_payments_are_not_configured(sys_conn, monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    tenant = _company(sys_conn)
    with pytest.raises(service.BillingError) as err:
        service.create_checkout(sys_conn, sys_conn, tenant, "o@example.com", "Co", "growth", "monthly")
    assert err.value.status == 503 and err.value.code == "payments_not_configured"


def test_checkout_reuses_the_customer_and_sends_the_expected_session(sys_conn, stripe_prices, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("APP_BASE_URL", "https://app.example")
    monkeypatch.setenv("PUBLIC_FRONTEND_ORIGIN", "https://app.example")
    tenant = _company(sys_conn)
    calls = {"customers": 0}

    def fake_customer(email, name, tenant_id, idempotency_key):
        calls["customers"] += 1
        return {"id": calls.setdefault("cid", f"cus_{uuid.uuid4().hex[:10]}")}

    def fake_session(params, idempotency_key):
        calls["params"], calls["key"] = params, idempotency_key
        calls["sessions"] = calls.get("sessions", 0) + 1
        return {"id": "cs_" + tenant, "url": "https://checkout.stripe.com/c/cs_" + tenant}

    monkeypatch.setattr(stripe_api, "create_customer", fake_customer)
    monkeypatch.setattr(stripe_api, "create_checkout_session", fake_session)
    monkeypatch.setattr(stripe_api, "retrieve_checkout_session", lambda sid: {
        "id": sid, "url": "https://checkout.stripe.com/c/" + sid, "status": "open",
    })
    result = service.create_checkout(sys_conn, sys_conn, tenant, "owner@example.com", "Co", "growth", "six-months")
    service.create_checkout(sys_conn, sys_conn, tenant, "owner@example.com", "Co", "growth", "six-months")

    assert result["url"].startswith("https://checkout.stripe.com/")
    assert calls["customers"] == 1  # stored and reused, never looked up by email
    assert calls["sessions"] == 1
    params = calls["params"]
    assert params["mode"] == "subscription" and params["customer"] == calls["cid"]
    assert params["line_items"] == [{"price": stripe_prices[("growth", "six-months")], "quantity": 1}]
    assert params["client_reference_id"] == tenant and params["subscription_data"]["metadata"]["tenant_id"] == tenant
    assert params["success_url"].startswith("https://app.example/billing?checkout=success")
    assert calls["key"].startswith("apex-checkout-")


def test_checkout_refuses_a_plan_that_is_not_bought_online(sys_conn, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    tenant = _company(sys_conn)
    with pytest.raises(service.BillingError) as err:
        service.create_checkout(sys_conn, sys_conn, tenant, "o@example.com", "Co", "custom", "monthly")
    assert err.value.status in (400, 404)


def _signed(payload: bytes, secret=WEBHOOK_SECRET) -> str:
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    from fastapi.testclient import TestClient
    from src.ai.main import app

    return TestClient(app)


@pytest.fixture
def billing_http_client():
    """Mount the production billing router in a small HTTP app for native tests."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.ai.core.exceptions import register_exception_handlers
    from src.ai.routers.billing import router

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    with TestClient(app) as test_client:
        yield test_client


def _event(event_type, obj, created=None):
    return {
        "id": f"evt_{uuid.uuid4().hex}", "object": "event", "type": event_type,
        "created": created or int(time.time()), "data": {"object": obj}, "livemode": False,
    }


def test_the_webhook_rejects_a_bad_signature(client):
    payload = json.dumps(_event("ping", {})).encode()
    response = client.post("/billing/webhook", content=payload, headers={"Stripe-Signature": _signed(payload, "whsec_wrong")})
    assert response.status_code == 400


def test_a_paid_checkout_activates_the_plan_and_duplicates_are_ignored(client, sys_conn, stripe_prices, monkeypatch):
    tenant = _company(sys_conn)
    store.start_trial(sys_conn, tenant)
    sys_conn.commit()
    sub_id, customer = f"sub_{uuid.uuid4().hex[:10]}", f"cus_{uuid.uuid4().hex[:10]}"
    live = _stripe_sub(sub_id, customer, stripe_prices[("growth", "monthly")])
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda sid: live)

    event = _event("checkout.session.completed", {
        "object": "checkout.session", "mode": "subscription", "subscription": sub_id, "customer": customer,
        "client_reference_id": tenant, "metadata": {"tenant_id": tenant},
    })
    payload = json.dumps(event).encode()
    first = client.post("/billing/webhook", content=payload, headers={"Stripe-Signature": _signed(payload)})
    again = client.post("/billing/webhook", content=payload, headers={"Stripe-Signature": _signed(payload)})
    assert first.status_code == 200 and first.json()["duplicate"] is False
    assert again.json()["duplicate"] is True

    plan = usage.get_plan(sys_conn, tenant)
    assert (plan["plan_key"], plan["status"], plan["source"]) == ("growth", "active", "stripe")
    assert store.customer_id(sys_conn, tenant) == customer
    with sys_conn.cursor() as cursor:
        cursor.execute("SELECT processed_at IS NOT NULL, tenant_id FROM billing_webhook_events WHERE stripe_event_id = %s;", (event["id"],))
        processed, stored_tenant = cursor.fetchone()
    assert processed and str(stored_tenant) == tenant


def test_a_late_stale_event_cannot_roll_back_newer_state(client, sys_conn, stripe_prices, monkeypatch):
    tenant = _company(sys_conn)
    sub_id, customer = f"sub_{uuid.uuid4().hex[:10]}", f"cus_{uuid.uuid4().hex[:10]}"
    store.save_customer(sys_conn, tenant, customer)
    sys_conn.commit()
    # Stripe's current state: active on six-months, set to cancel at period end.
    live = _stripe_sub(sub_id, customer, stripe_prices[("growth", "six-months")], status="active", cancel=True)
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda sid: live)
    # An old "updated" event whose payload still says past_due on monthly.
    stale_obj = _stripe_sub(sub_id, customer, stripe_prices[("growth", "monthly")], status="past_due")
    event = _event("customer.subscription.updated", stale_obj, created=int(time.time()) - 3600)
    payload = json.dumps(event).encode()
    assert client.post("/billing/webhook", content=payload, headers={"Stripe-Signature": _signed(payload)}).status_code == 200
    sub = store.current_subscription(sys_conn, tenant)
    assert (sub["status"], sub["period_code"], sub["cancel_at_period_end"]) == ("active", "six-months", True)


def test_a_failed_renewal_records_the_payment_and_removes_access(client, sys_conn, stripe_prices, monkeypatch):
    tenant = _company(sys_conn)
    sub_id, customer = f"sub_{uuid.uuid4().hex[:10]}", f"cus_{uuid.uuid4().hex[:10]}"
    store.save_customer(sys_conn, tenant, customer)
    sys_conn.commit()
    monkeypatch.setattr(stripe_api, "retrieve_subscription",
                        lambda sid: _stripe_sub(sub_id, customer, stripe_prices[("starter", "monthly")], status="past_due"))
    invoice = {
        "id": f"in_{uuid.uuid4().hex[:10]}", "object": "invoice", "subscription": sub_id, "customer": customer,
        "amount_due": 4900, "amount_paid": 0, "currency": "usd", "hosted_invoice_url": "https://invoice.stripe.com/i/1",
    }
    monkeypatch.setattr(stripe_api, "retrieve_invoice", lambda invoice_id: invoice)
    payload = json.dumps(_event("invoice.payment_failed", invoice)).encode()
    assert client.post("/billing/webhook", content=payload, headers={"Stripe-Signature": _signed(payload)}).status_code == 200
    plan = usage.get_plan(sys_conn, tenant)
    assert (plan["plan_key"], plan["status"]) == ("starter", "past_due")
    payments = store.payments(sys_conn, tenant)
    assert payments[0]["status"] == "failed" and payments[0]["amount"] == 49.0


def test_delayed_payment_failure_cannot_downgrade_a_paid_invoice(client, sys_conn, stripe_prices, monkeypatch):
    tenant = _company(sys_conn)
    sub_id, customer = f"sub_{uuid.uuid4().hex[:10]}", f"cus_{uuid.uuid4().hex[:10]}"
    store.save_customer(sys_conn, tenant, customer)
    sys_conn.commit()
    monkeypatch.setattr(
        stripe_api,
        "retrieve_subscription",
        lambda sid: _stripe_sub(sub_id, customer, stripe_prices[("starter", "monthly")]),
    )
    invoice = {
        "id": f"in_{uuid.uuid4().hex[:10]}", "object": "invoice", "subscription": sub_id,
        "customer": customer, "status": "paid", "paid": True, "amount_due": 4900,
        "amount_paid": 4900, "currency": "usd", "hosted_invoice_url": "https://invoice.stripe.com/i/paid",
        "status_transitions": {"paid_at": int(time.time())},
    }
    monkeypatch.setattr(stripe_api, "retrieve_invoice", lambda invoice_id: invoice)

    for event_type in ("invoice.payment_succeeded", "invoice.payment_failed"):
        payload = json.dumps(_event(event_type, {**invoice, "status": "open" if event_type.endswith("failed") else "paid"})).encode()
        response = client.post("/billing/webhook", content=payload, headers={"Stripe-Signature": _signed(payload)})
        assert response.status_code == 200, response.text

    payments = store.payments(sys_conn, tenant)
    assert len(payments) == 1
    assert payments[0]["status"] == "succeeded"
    assert payments[0]["amount"] == 49.0


def test_terminal_event_for_old_subscription_does_not_disable_replacement(
    client, sys_conn, stripe_prices, monkeypatch
):
    tenant = _company(sys_conn)
    customer = f"cus_{uuid.uuid4().hex[:10]}"
    old_id, new_id = f"sub_{uuid.uuid4().hex[:10]}", f"sub_{uuid.uuid4().hex[:10]}"
    store.save_customer(sys_conn, tenant, customer)
    old = _stripe_sub(old_id, customer, stripe_prices[("starter", "monthly")])
    new = _stripe_sub(new_id, customer, stripe_prices[("growth", "monthly")])
    store.apply_subscription(sys_conn, tenant, old, "starter", "monthly", datetime.now(timezone.utc))
    canceled_old = _stripe_sub(old_id, customer, stripe_prices[("starter", "monthly")], status="canceled")
    store.apply_subscription(sys_conn, tenant, canceled_old, "starter", "monthly", datetime.now(timezone.utc))
    store.apply_subscription(sys_conn, tenant, new, "growth", "monthly", datetime.now(timezone.utc))
    sys_conn.commit()

    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda sid: canceled_old if sid == old_id else new)
    payload = json.dumps(_event("customer.subscription.deleted", {"id": old_id})).encode()
    response = client.post("/billing/webhook", content=payload, headers={"Stripe-Signature": _signed(payload)})

    assert response.status_code == 200, response.text
    plan = usage.get_plan(sys_conn, tenant)
    assert (plan["plan_key"], plan["status"], plan["source"]) == ("growth", "active", "stripe")
    assert store.current_subscription(sys_conn, tenant)["stripe_subscription_id"] == new_id


def test_an_event_for_an_unknown_company_is_retried_not_dropped(client, stripe_prices, monkeypatch):
    sub_id = f"sub_{uuid.uuid4().hex[:10]}"
    monkeypatch.setattr(stripe_api, "retrieve_subscription",
                        lambda sid: _stripe_sub(sub_id, f"cus_{uuid.uuid4().hex[:8]}", stripe_prices[("growth", "monthly")]))
    payload = json.dumps(_event("customer.subscription.updated", {"id": sub_id})).encode()
    assert client.post("/billing/webhook", content=payload, headers={"Stripe-Signature": _signed(payload)}).status_code == 500


def test_a_company_can_only_read_its_own_billing_rows(sys_conn):
    from src.ai import db

    a, b = _company(sys_conn), _company(sys_conn)
    store.save_customer(sys_conn, a, f"cus_{uuid.uuid4().hex[:10]}")
    sys_conn.commit()
    with sys_conn.cursor() as cursor:
        # Create the user: a fresh database has none, and this test must not
        # depend on rows another test happened to leave behind.
        cursor.execute(
            "INSERT INTO users (email, password_hash) VALUES (%s, 'x') RETURNING user_id;",
            (f"billing-iso-{uuid.uuid4().hex[:10]}@example.com",),
        )
        any_user = str(cursor.fetchone()[0])
    sys_conn.commit()
    conn_b = db.dedicated_tenant_connection(b, any_user)
    try:
        assert store.customer_id(conn_b, a) is None
        with conn_b.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM billing_customers;")
            assert cursor.fetchone()[0] == 0
            with pytest.raises(psycopg2.Error):
                cursor.execute("INSERT INTO billing_customers (tenant_id, stripe_customer_id) VALUES (%s, 'cus_forged');", (b,))
    finally:
        conn_b.rollback()
        conn_b.close()


def test_payments_flag_follows_the_secret(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    assert config.payments_enabled() is False
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    assert config.payments_enabled() is True


def test_today_is_a_date():  # guards the trial-expiry comparison type
    assert isinstance(datetime.now(timezone.utc).date(), date)


def _tenant_billing_state(conn, tenant_ids):
    """Stable snapshots for read-only subscription/usage/credit assertions."""
    tables = (
        "tenant_plan_assignments",
        "billing_subscriptions",
        "billing_trials",
        "billing_customers",
        "billing_payments",
        "tenant_usage_counters",
        "tenant_credit_balances",
        "usage_ledger",
        "usage_ledger_adjustments",
    )
    state = {}
    with conn.cursor() as cursor:
        for table in tables:
            cursor.execute(
                f"SELECT to_jsonb(row_data) FROM {table} AS row_data "
                "WHERE tenant_id = ANY(%s::uuid[]) ORDER BY to_jsonb(row_data)::text;",
                (tenant_ids,),
            )
            state[table] = [row[0] for row in cursor.fetchall()]
    return state


def test_subscription_effective_rights_are_tenant_isolated_and_read_only(billing_http_client, sys_conn):
    """Exercise the authenticated route over PostgreSQL with the real app role/RLS."""
    from src.ai import db
    from src.ai.core.security import create_access_token

    tenant_a, tenant_b = _company(sys_conn), _company(sys_conn)
    user_a, user_b, outsider = (str(uuid.uuid4()) for _ in range(3))
    tenants = [tenant_a, tenant_b]
    users = [user_a, user_b, outsider]
    with sys_conn.cursor() as cursor:
        for user_id, label in ((user_a, "a"), (user_b, "b"), (outsider, "outsider")):
            cursor.execute(
                "INSERT INTO users (user_id, email, password_hash, full_name, email_verified_at) "
                "VALUES (%s, %s, 'not-a-login-password', %s, NOW());",
                (user_id, f"b3-{label}-{user_id}@example.test", f"B3 {label}"),
            )
        cursor.execute(
            "INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, 'owner'), (%s, %s, 'owner');",
            (tenant_a, user_a, tenant_b, user_b),
        )
        cursor.execute(
            "INSERT INTO tenant_plan_assignments (tenant_id, plan_key, status, source) "
            "VALUES (%s, 'starter', 'active', 'manual'), (%s, 'growth', 'active', 'manual');",
            (tenant_a, tenant_b),
        )
        cursor.execute(
            "SELECT plan_key, limit_value FROM usage_plan_limits "
            "WHERE feature_code = 'tracked_products' AND plan_key IN ('starter', 'growth');"
        )
        expected_limits = dict(cursor.fetchall())
    sys_conn.commit()

    assert set(expected_limits) == {"starter", "growth"}
    assert expected_limits["starter"] != expected_limits["growth"]
    token_a, _ = create_access_token(tenant_a, user_a, email_verified=True)
    token_b, _ = create_access_token(tenant_b, user_b, email_verified=True)
    forged_cross_tenant_token, _ = create_access_token(tenant_a, user_b, email_verified=True)
    before = _tenant_billing_state(sys_conn, tenants)

    try:
        assert billing_http_client.get("/billing/subscription").status_code == 401
        denied = billing_http_client.get(
            "/billing/subscription",
            headers={"Authorization": f"Bearer {forged_cross_tenant_token}"},
        )
        assert denied.status_code == 403

        response_a = billing_http_client.get(
            "/billing/subscription", headers={"Authorization": f"Bearer {token_a}"}
        )
        response_b = billing_http_client.get(
            "/billing/subscription", headers={"Authorization": f"Bearer {token_b}"}
        )
        assert response_a.status_code == response_b.status_code == 200

        legacy_fields = {
            "available", "planId", "planName", "status", "hasAccess", "assigned", "source",
            "billingPeriod", "periodStart", "periodEnd", "trialEndsAt", "trialUsed", "renewsAt",
            "endsAt", "cancelAtPeriodEnd", "scheduledChange", "hasSubscription", "hasBillingAccount",
            "canManageBilling", "paymentsEnabled", "limits", "usage", "features", "entitlements",
            "credits", "trialAvailable", "trialEndsAtExact",
        }
        expected_top_level = legacy_fields | {"effectiveRights", "currentPrice", "checkoutTrialEndsAt"}
        for response in (response_a.json(), response_b.json()):
            assert set(response) == expected_top_level
            assert response["checkoutTrialEndsAt"] is None  # no preserved trial exists for these two fixtures
            if response["currentPrice"] is not None:
                assert set(response["currentPrice"]) == {"amount", "currency", "intervalUnit", "intervalCount"}
            rights = response["effectiveRights"]
            assert set(rights) == {"version", "basis", "items"}
            assert rights["version"] == 1 and rights["basis"] == "configured_plan"
            assert all(
                set(item) == {"featureCode", "state", "unit", "aggregationType", "resetCycle", "limit"}
                for item in rights["items"]
            )

        def tracked_product_limit(response):
            items = response["effectiveRights"]["items"]
            return next(item["limit"] for item in items if item["featureCode"] == "tracked_products")

        assert tracked_product_limit(response_a.json()) == expected_limits["starter"]
        assert tracked_product_limit(response_b.json()) == expected_limits["growth"]
        assert tracked_product_limit(response_a.json()) != tracked_product_limit(response_b.json())
        assert "tenant_id" not in response_a.json()["effectiveRights"]
        assert "tenant_id" not in response_b.json()["effectiveRights"]
        assert _tenant_billing_state(sys_conn, tenants) == before
    finally:
        db.close_pool()
        sys_conn.rollback()
        with sys_conn.cursor() as cursor:
            cursor.execute("DELETE FROM companies WHERE tenant_id = ANY(%s::uuid[]);", (tenants,))
            cursor.execute("DELETE FROM users WHERE user_id = ANY(%s::uuid[]);", (users,))
        sys_conn.commit()


def test_two_simultaneous_deliveries_of_one_event_process_it_once(sys_conn, stripe_prices, monkeypatch):
    """Stripe retries / replays can arrive together. The event must run exactly once;
    the other delivery waits, then is acknowledged as a duplicate."""
    import threading

    tenant = _company(sys_conn)
    sys_conn.commit()
    event = _event("customer.subscription.updated", {"id": "sub_race"})
    runs, results, errors = [], [], []

    def slow_sync(conn, subscription_id, created, hint=None):
        runs.append(subscription_id)
        time.sleep(1.0)  # long enough for the second delivery to arrive mid-processing
        return tenant

    monkeypatch.setattr(webhooks, "sync_subscription", slow_sync)

    def deliver():
        conn = psycopg2.connect(DATABASE_URL)
        try:
            results.append(webhooks.handle_event(conn, event)["duplicate"])
        except Exception as err:  # noqa: BLE001
            errors.append(err)
        finally:
            conn.close()

    threads = [threading.Thread(target=deliver) for _ in range(4)]
    [t.start() for t in threads]
    [t.join(timeout=60) for t in threads]
    assert not errors, errors
    assert len(runs) == 1, f"event ran {len(runs)} times"
    assert sorted(results) == [False, True, True, True]


def test_a_failed_event_is_retried_not_swallowed_as_a_duplicate(sys_conn, monkeypatch):
    event = _event("customer.subscription.updated", {"id": "sub_retry"})
    attempts = []

    def flaky(conn, subscription_id, created, hint=None):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("temporary")
        return None

    monkeypatch.setattr(webhooks, "sync_subscription", flaky)
    with pytest.raises(webhooks.WebhookRetry):
        webhooks.handle_event(sys_conn, event)
    assert webhooks.handle_event(sys_conn, event)["duplicate"] is False  # Stripe's retry runs it again
    assert webhooks.handle_event(sys_conn, event)["duplicate"] is True    # and only once
    assert len(attempts) == 2

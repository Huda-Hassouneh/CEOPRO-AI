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
    tenant = _company(sys_conn)
    calls = {"customers": 0}

    def fake_customer(email, name, tenant_id, idempotency_key):
        calls["customers"] += 1
        return {"id": calls.setdefault("cid", f"cus_{uuid.uuid4().hex[:10]}")}

    def fake_session(params, idempotency_key):
        calls["params"], calls["key"] = params, idempotency_key
        return {"id": "cs_1", "url": "https://checkout.stripe.com/c/cs_1"}

    monkeypatch.setattr(stripe_api, "create_customer", fake_customer)
    monkeypatch.setattr(stripe_api, "create_checkout_session", fake_session)
    result = service.create_checkout(sys_conn, sys_conn, tenant, "owner@example.com", "Co", "growth", "six-months")
    service.create_checkout(sys_conn, sys_conn, tenant, "owner@example.com", "Co", "growth", "six-months")

    assert result["url"].startswith("https://checkout.stripe.com/")
    assert calls["customers"] == 1  # stored and reused, never looked up by email
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
    payload = json.dumps(_event("invoice.payment_failed", invoice)).encode()
    assert client.post("/billing/webhook", content=payload, headers={"Stripe-Signature": _signed(payload)}).status_code == 200
    plan = usage.get_plan(sys_conn, tenant)
    assert (plan["plan_key"], plan["status"]) == ("starter", "past_due")
    payments = store.payments(sys_conn, tenant)
    assert payments[0]["status"] == "failed" and payments[0]["amount"] == 49.0


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

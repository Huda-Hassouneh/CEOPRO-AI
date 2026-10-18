"""
End to end against the REAL Stripe API in TEST MODE and a real Postgres:
Checkout session creation, a paid subscription, the signed webhook (signature,
replay window, duplicates), plan/status sync, cancel/resume and an upgrade.

Skipped - and reported as skipped, never as passed - unless all of these are set:

    AI_TEST_DATABASE_URL            a migrated Postgres
    STRIPE_E2E_SECRET_KEY           a Stripe TEST key (sk_test_... or rk_test_...)
    STRIPE_E2E_WEBHOOK_SECRET       a whsec_... signing secret (used to sign the
                                    events this test posts to the in-process app)
    and `python -m scripts.stripe_sync_catalog` already run against that database.

Test mode only: a live key is refused. The payment uses Stripe's published test
payment method token (pm_card_visa), so no card number is ever handled. Every
Stripe object the test creates is a test-mode customer/subscription; the
subscription is cancelled at the end. The subscription's own events are also
delivered by Stripe to whatever webhook endpoint the account has registered
(e.g. staging), which will not know this throwaway company - expect those
deliveries to be retried and ignored there.
"""
import hashlib
import hmac
import json
import os
import time
import uuid

import psycopg2
import pytest

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
STRIPE_KEY = os.getenv("STRIPE_E2E_SECRET_KEY", "")
WEBHOOK_SECRET = os.getenv("STRIPE_E2E_WEBHOOK_SECRET", "")

pytestmark = [
    pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - Stripe test-mode e2e SKIPPED"),
    pytest.mark.skipif(not (STRIPE_KEY and WEBHOOK_SECRET),
                       reason="STRIPE_E2E_SECRET_KEY / STRIPE_E2E_WEBHOOK_SECRET not set - Stripe test-mode e2e SKIPPED"),
    pytest.mark.skipif(bool(STRIPE_KEY) and not STRIPE_KEY.startswith(("sk_test_", "rk_test_")),
                       reason="STRIPE_E2E_SECRET_KEY is not a test-mode key - refusing to run"),
]


@pytest.fixture
def sys_conn():
    conn = psycopg2.connect(DATABASE_URL)
    yield conn
    conn.rollback()
    conn.close()


def _signed(payload: bytes, secret=None, ts=None) -> str:
    ts = int(time.time()) if ts is None else ts
    sig = hmac.new((secret or WEBHOOK_SECRET).encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def _event(event_type, obj):
    return {"id": f"evt_e2e_{uuid.uuid4().hex}", "object": "event", "type": event_type,
            "created": int(time.time()), "data": {"object": obj}, "livemode": False}


@pytest.fixture
def world(sys_conn, monkeypatch):
    """A throwaway company with an owner, the app wired to the test Stripe account."""
    import stripe

    monkeypatch.setenv("STRIPE_SECRET_KEY", STRIPE_KEY)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setenv("APP_BASE_URL", "http://localhost:5173")
    with sys_conn.cursor() as cursor:
        cursor.execute("SELECT plan_key, period_code, stripe_price_id FROM billing_plan_prices "
                       "WHERE retired_at IS NULL AND period_code = 'monthly' AND stripe_price_id IS NOT NULL;")
        prices = {(plan, period): price for plan, period, price in cursor.fetchall()}
    if ("starter", "monthly") not in prices or ("growth", "monthly") not in prices:
        pytest.skip("Stripe prices not synced into this database - run `python -m scripts.stripe_sync_catalog` first")

    tenant, user = str(uuid.uuid4()), str(uuid.uuid4())
    with sys_conn.cursor() as cursor:
        cursor.execute("INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
                       "VALUES (%s, %s, 'JO', 'JOD');", (tenant, f"E2E {tenant[:8]}"))
        cursor.execute("INSERT INTO users (user_id, email, password_hash) VALUES (%s, %s, 'x');",
                       (user, f"e2e-{tenant[:8]}@example.com"))
        cursor.execute("INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, 'owner');", (tenant, user))
    sys_conn.commit()

    from fastapi.testclient import TestClient
    from src.ai.core.security import create_access_token
    from src.ai.main import app

    token, _ = create_access_token(tenant, user)
    stripe.api_key = STRIPE_KEY
    created = {"subscriptions": []}
    yield {"tenant": tenant, "user": user, "prices": prices, "stripe": stripe, "created": created,
           "client": TestClient(app), "auth": {"Authorization": f"Bearer {token}"}}
    for sub_id in created["subscriptions"]:  # leave the test account clean
        try:
            stripe.Subscription.cancel(sub_id)
        except Exception:  # noqa: BLE001 - already cancelled
            pass


def _json_default(value):  # the SDK returns some amounts as Decimal; Stripe's JSON has plain numbers
    from decimal import Decimal

    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _post_event(client, event, **kw):
    payload = json.dumps(event, default=_json_default).encode()
    return client.post("/billing/webhook", content=payload, headers={"Stripe-Signature": _signed(payload, **kw)})


def test_checkout_subscription_webhooks_cancel_resume_and_upgrade(world, sys_conn):
    client, auth, tenant, stripe = world["client"], world["auth"], world["tenant"], world["stripe"]
    std_price, plus_price = world["prices"][("starter", "monthly")], world["prices"][("growth", "monthly")]

    # --- 1. Checkout: a real Stripe session for the Standard monthly price ---
    first = client.post("/billing/checkout", json={"plan_key": "starter", "period_code": "monthly"}, headers=auth)
    assert first.status_code == 200, first.text
    session_id = first.json()["session_id"]
    assert first.json()["url"].startswith("https://checkout.stripe.com/")
    session = stripe.checkout.Session.retrieve(session_id, expand=["line_items"])
    assert session.mode == "subscription" and session.livemode is False
    assert session.client_reference_id == tenant
    assert session.line_items.data[0].price.id == std_price
    assert session.amount_total == 5500  # $55.00
    again = client.post("/billing/checkout", json={"plan_key": "starter", "period_code": "monthly"}, headers=auth)
    assert again.json()["session_id"] == session_id, "a double click must not open a second checkout"

    # --- 2. A paid subscription (hosted card entry replaced by Stripe's test PM token) ---
    with sys_conn.cursor() as cursor:
        cursor.execute("SELECT stripe_customer_id FROM billing_customers WHERE tenant_id = %s;", (tenant,))
        customer = cursor.fetchone()[0]
    pm = stripe.PaymentMethod.attach("pm_card_visa", customer=customer)
    stripe.Customer.modify(customer, invoice_settings={"default_payment_method": pm.id})
    sub = stripe.Subscription.create(
        customer=customer, items=[{"price": std_price}], default_payment_method=pm.id,
        metadata={"tenant_id": tenant, "plan_key": "starter", "period_code": "monthly"},
    )
    world["created"]["subscriptions"].append(sub.id)
    assert sub.status == "active" and sub.livemode is False
    invoice = stripe.Invoice.retrieve(sub.latest_invoice).to_dict()
    assert invoice["amount_paid"] == 5500

    # --- 3. Webhook: signature checked, plan activated only from the verified event ---
    assert client.get("/billing/subscription", headers=auth).json()["hasSubscription"] is False
    completed = _event("checkout.session.completed", {
        "object": "checkout.session", "mode": "subscription", "subscription": sub.id, "customer": customer,
        "client_reference_id": tenant, "metadata": {"tenant_id": tenant}})
    result = _post_event(client, completed)
    assert result.status_code == 200 and result.json()["duplicate"] is False, result.text
    paid = _post_event(client, _event("invoice.paid", invoice))
    assert paid.status_code == 200, paid.text

    state = client.get("/billing/subscription", headers=auth).json()
    assert (state["planId"], state["status"], state["hasAccess"]) == ("starter", "active", True)
    assert state["limits"]["products"] == 100 and state["limits"]["reports"] == 5 and state["limits"]["teamSeats"] == 5
    with sys_conn.cursor() as cursor:
        cursor.execute("SELECT status, plan_key, stripe_subscription_id FROM billing_subscriptions WHERE tenant_id = %s;", (tenant,))
        assert cursor.fetchall() == [("active", "starter", sub.id)]
        cursor.execute("SELECT status, amount FROM billing_payments WHERE tenant_id = %s;", (tenant,))
        assert [(s, float(a)) for s, a in cursor.fetchall()] == [("succeeded", 55.0)]
    sys_conn.rollback()

    # --- 4. Idempotency: the same event again changes nothing ---
    payload = json.dumps(completed).encode()
    replay = client.post("/billing/webhook", content=payload, headers={"Stripe-Signature": _signed(payload)})
    assert replay.status_code == 200 and replay.json()["duplicate"] is True
    with sys_conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM billing_subscriptions WHERE tenant_id = %s;", (tenant,))
        assert cursor.fetchone()[0] == 1
    sys_conn.rollback()

    # --- 5. Signature validation and replay protection ---
    body = json.dumps(_event("customer.subscription.updated", {"id": sub.id})).encode()
    assert client.post("/billing/webhook", content=body).status_code == 400                        # no header
    assert client.post("/billing/webhook", content=body,
                       headers={"Stripe-Signature": _signed(body, secret="whsec_wrong")}).status_code == 400
    tampered = client.post("/billing/webhook", content=body + b" ", headers={"Stripe-Signature": _signed(body)})
    assert tampered.status_code == 400                                                              # body changed
    stale = client.post("/billing/webhook", content=body, headers={"Stripe-Signature": _signed(body, ts=int(time.time()) - 3600)})
    assert stale.status_code == 400                                                                 # outside 5-minute window

    # --- 6. Cancel at period end, then resume ---
    assert client.post("/billing/cancel", headers=auth).status_code == 200
    assert _post_event(client, _event("customer.subscription.updated", {"id": sub.id})).status_code == 200
    cancelling = client.get("/billing/subscription", headers=auth).json()
    assert cancelling["cancelAtPeriodEnd"] is True and cancelling["hasAccess"] is True
    assert client.post("/billing/resume", headers=auth).status_code == 200
    assert _post_event(client, _event("customer.subscription.updated", {"id": sub.id})).status_code == 200
    assert client.get("/billing/subscription", headers=auth).json()["cancelAtPeriodEnd"] is False

    # --- 7. Upgrade Standard -> Plus: new limits only after the verified event ---
    upgrade = client.post("/billing/change-plan", json={"plan_key": "growth", "period_code": "monthly"}, headers=auth)
    assert upgrade.status_code == 200, upgrade.text
    live = stripe.Subscription.retrieve(sub.id)
    assert live["items"]["data"][0]["price"]["id"] == plus_price
    assert _post_event(client, _event("customer.subscription.updated", {"id": sub.id})).status_code == 200
    plus = client.get("/billing/subscription", headers=auth).json()
    assert (plus["planId"], plus["status"]) == ("growth", "active")
    assert plus["limits"]["products"] == 250 and plus["limits"]["reports"] == 20 and plus["limits"]["teamSeats"] == 20

    # --- 8. Cancellation at Stripe: access ends only via the verified event ---
    stripe.Subscription.cancel(sub.id)
    assert _post_event(client, _event("customer.subscription.deleted", {"id": sub.id})).status_code == 200
    ended = client.get("/billing/subscription", headers=auth).json()
    assert ended["hasAccess"] is False, ended

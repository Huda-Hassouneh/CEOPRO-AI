"""Real SQL through the unchanged billing router/services; Stripe HTTP is doubled.

These tests deliberately do not implement or test new entitlement policy.
The existing webhook's assignment update is verified as part of state sync.
"""

import json
import os
import threading
import time
import uuid

import pytest

from src.ai.billing import service, store, stripe_api, webhooks
from src.ai.core.security import create_access_token

from .test_contract import signed


def live_subscription(tenant, price, *, status="active", cancel=False):
    now = int(time.time())
    return {
        "id": "sub_test_" + uuid.uuid4().hex,
        "object": "subscription",
        "customer": "cus_test_" + uuid.uuid4().hex,
        "status": status,
        "cancel_at_period_end": cancel,
        "canceled_at": None,
        "trial_end": None,
        "schedule": None,
        "metadata": {"tenant_id": tenant},
        "items": {
            "data": [
                {
                    "id": "si_test",
                    "price": {"id": price},
                    "current_period_start": now,
                    "current_period_end": now + 30 * 86400,
                }
            ]
        },
    }


@pytest.fixture
def deliver(client, monkeypatch, owner_db, billing_connections):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_offline")
    ids = []

    def send(kind, obj, *, event_id=None, created=None):
        event_id = event_id or "evt_test_" + uuid.uuid4().hex
        ids.append(event_id)
        payload = json.dumps(
            {
                "id": event_id,
                "object": "event",
                "type": kind,
                "livemode": False,
                "created": created or int(time.time()),
                "data": {"object": obj},
            }
        ).encode()
        return client.post(
            "/billing/webhook",
            content=payload,
            headers={"Stripe-Signature": signed(payload, "whsec_offline")},
        )

    yield send
    owner_db.rollback()
    with owner_db.cursor() as cur:
        cur.execute(
            "DELETE FROM billing_webhook_events WHERE stripe_event_id=ANY(%s)", (ids,)
        )
    owner_db.commit()


def test_checkout_links_existing_tenant_and_reuses_customer(
    owner_db, tenant, test_price, monkeypatch
):
    tid, _ = tenant
    plan, price = test_price
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_offline")
    calls = []
    monkeypatch.setattr(
        stripe_api,
        "create_customer",
        lambda email, name, tenant_id, idempotency_key: (
            calls.append((tenant_id, idempotency_key)) or {"id": "cus_test_" + tid}
        ),
    )
    requests = []
    monkeypatch.setattr(
        stripe_api,
        "create_checkout_session",
        lambda params, idempotency_key: (
            requests.append((params, idempotency_key))
            or {"id": "cs_test_fixture", "url": "https://checkout.stripe.com/test"}
        ),
    )
    first = service.create_checkout(
        owner_db, owner_db, tid, "owner@example.test", "Fixture", plan, "monthly"
    )
    second = service.create_checkout(
        owner_db, owner_db, tid, "owner@example.test", "Fixture", plan, "monthly"
    )
    assert first == second
    assert len(calls) == 1
    assert store.customer_id(owner_db, tid) == "cus_test_" + tid
    assert requests[0][0]["client_reference_id"] == tid
    assert requests[0][0]["line_items"] == [{"price": price, "quantity": 1}]
    assert store.current_subscription(owner_db, tid) is None, (
        "Checkout redirect is not payment confirmation"
    )


def test_signed_checkout_persists_once_and_replayed_events_do_not_duplicate(
    deliver, owner_db, tenant, test_price, monkeypatch
):
    tid, _ = tenant
    plan, price = test_price
    live = live_subscription(tid, price)
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda sid: live)
    event_id = "evt_test_" + uuid.uuid4().hex
    obj = {
        "mode": "subscription",
        "subscription": live["id"],
        "customer": live["customer"],
        "client_reference_id": tid,
    }
    assert deliver("checkout.session.completed", obj, event_id=event_id).json() == {
        "received": True,
        "duplicate": False,
    }
    assert deliver("checkout.session.completed", obj, event_id=event_id).json() == {
        "received": True,
        "duplicate": True,
    }
    sub = store.current_subscription(owner_db, tid)
    assert sub["stripe_subscription_id"] == live["id"]
    assert (sub["plan_key"], sub["status"]) == (plan, "active")
    with owner_db.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM billing_subscriptions WHERE tenant_id=%s", (tid,)
        )
        assert cur.fetchone()[0] == 1
        cur.execute(
            "SELECT plan_key,status,source FROM tenant_plan_assignments WHERE tenant_id=%s",
            (tid,),
        )
        assert cur.fetchone() == (plan, "active", "stripe")


@pytest.mark.parametrize(
    "provider_status,local_status",
    [
        ("trialing", "trialing"),
        ("active", "active"),
        ("past_due", "past_due"),
        ("unpaid", "payment_failed"),
        ("incomplete", "pending"),
        ("paused", "paused"),
        ("canceled", "cancelled"),
        ("incomplete_expired", "expired"),
    ],
)
def test_subscription_lifecycle_is_synchronized_to_existing_rows(
    deliver, owner_db, tenant, test_price, monkeypatch, provider_status, local_status
):
    tid, _ = tenant
    _, price = test_price
    live = live_subscription(tid, price, status=provider_status)
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda sid: live)
    response = deliver("customer.subscription.updated", {"id": live["id"]})
    assert response.status_code == 200, response.text
    with owner_db.cursor() as cur:
        cur.execute(
            "SELECT status FROM billing_subscriptions WHERE stripe_subscription_id=%s",
            (live["id"],),
        )
        assert cur.fetchone()[0] == local_status
        cur.execute(
            "SELECT status FROM tenant_plan_assignments WHERE tenant_id=%s", (tid,)
        )
        assert cur.fetchone()[0] == local_status


def test_stale_event_payload_cannot_replace_current_provider_state(
    deliver, owner_db, tenant, test_price, monkeypatch
):
    tid, _ = tenant
    _, price = test_price
    live = live_subscription(tid, price, cancel=True)
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda sid: live)
    response = deliver(
        "customer.subscription.updated",
        {**live, "status": "past_due", "cancel_at_period_end": False},
        created=int(time.time()) - 3600,
    )
    assert response.status_code == 200
    sub = store.current_subscription(owner_db, tid)
    assert (sub["status"], sub["cancel_at_period_end"]) == ("active", True)


def test_payment_failure_then_success_is_one_invoice_record(
    deliver, owner_db, tenant, test_price, monkeypatch
):
    tid, _ = tenant
    _, price = test_price
    live = live_subscription(tid, price, status="past_due")
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda sid: live)
    invoice = {
        "id": "in_test_" + uuid.uuid4().hex,
        "object": "invoice",
        "customer": live["customer"],
        "parent": {
            "subscription_details": {
                "subscription": live["id"],
                "metadata": {"tenant_id": tid},
            }
        },
        "amount_due": 5500,
        "amount_paid": 0,
        "currency": "usd",
        "status": "open",
    }
    monkeypatch.setattr(stripe_api, "retrieve_invoice", lambda iid: invoice)
    assert deliver("invoice.payment_failed", invoice).status_code == 200
    assert store.payments(owner_db, tid)[0]["status"] == "failed"
    live["status"] = "active"
    invoice["amount_paid"] = 5500
    invoice["status"] = "paid"
    assert deliver("invoice.paid", invoice).status_code == 200
    assert deliver("invoice.payment_succeeded", invoice).status_code == 200
    rows = store.payments(owner_db, tid)
    assert len(rows) == 1
    assert (rows[0]["status"], rows[0]["amount"], rows[0]["currency"]) == (
        "succeeded",
        55.0,
        "USD",
    )


def test_provider_outage_event_retries_then_is_a_duplicate(
    deliver, owner_db, tenant, test_price, monkeypatch
):
    tid, _ = tenant
    _, price = test_price
    live = live_subscription(tid, price)
    eid = "evt_test_" + uuid.uuid4().hex
    monkeypatch.setattr(
        stripe_api,
        "retrieve_subscription",
        lambda sid: (_ for _ in ()).throw(RuntimeError("offline provider failure")),
    )
    assert (
        deliver(
            "customer.subscription.updated", {"id": live["id"]}, event_id=eid
        ).status_code
        == 500
    )
    with owner_db.cursor() as cur:
        cur.execute(
            "SELECT processed_at,error IS NOT NULL FROM billing_webhook_events WHERE stripe_event_id=%s",
            (eid,),
        )
        assert cur.fetchone() == (None, True)
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda sid: live)
    assert (
        deliver(
            "customer.subscription.updated", {"id": live["id"]}, event_id=eid
        ).json()["duplicate"]
        is False
    )
    assert (
        deliver(
            "customer.subscription.updated", {"id": live["id"]}, event_id=eid
        ).json()["duplicate"]
        is True
    )


def test_cancel_and_resume_wait_for_webhook_sync(
    client, deliver, owner_db, tenant, test_price, monkeypatch
):
    tid, uid = tenant
    _, price = test_price
    live = live_subscription(tid, price)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_offline")
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda sid: live)
    assert (
        deliver("customer.subscription.updated", {"id": live["id"]}).status_code == 200
    )
    modifications = []
    monkeypatch.setattr(
        stripe_api,
        "modify_subscription",
        lambda sid, **kw: modifications.append(kw) or live,
    )
    token, _ = create_access_token(tid, uid, email_verified=True)
    headers = {"Authorization": "Bearer " + token}
    assert client.post("/billing/cancel", headers=headers).status_code == 200
    assert modifications[-1]["cancel_at_period_end"] is True
    assert store.current_subscription(owner_db, tid)["cancel_at_period_end"] is False
    live["cancel_at_period_end"] = True
    assert (
        deliver("customer.subscription.updated", {"id": live["id"]}).status_code == 200
    )
    assert store.current_subscription(owner_db, tid)["cancel_at_period_end"] is True
    assert client.post("/billing/resume", headers=headers).status_code == 200
    assert modifications[-1]["cancel_at_period_end"] is False


@pytest.mark.parametrize(
    "role,expected",
    [
        ("owner", 200),
        ("admin", 200),
        ("accountant", 200),
        ("manager", 403),
        ("staff", 403),
    ],
)
def test_invoice_authorization_uses_existing_membership(
    client, owner_db, tenant, billing_connections, role, expected
):
    tid, uid = tenant
    with owner_db.cursor() as cur:
        cur.execute(
            "UPDATE tenant_users SET role_key=%s WHERE tenant_id=%s AND user_id=%s",
            (role, tid, uid),
        )
    owner_db.commit()
    token, _ = create_access_token(tid, uid, email_verified=True)
    response = client.get(
        "/billing/invoices", headers={"Authorization": "Bearer " + token}
    )
    assert response.status_code == expected, response.text


def test_restricted_runtime_role_cannot_forge_billing_or_read_another_tenant(
    owner_db, tenant, billing_connections
):
    import psycopg2

    tid, uid = tenant
    store.save_customer(owner_db, tid, "cus_test_" + tid)
    owner_db.commit()
    other = str(uuid.uuid4())
    with owner_db.cursor() as cur:
        cur.execute(
            "INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,'Other billing fixture','JO','JOD')",
            (other,),
        )
        cur.execute(
            "INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')",
            (other, uid),
        )
    conn = billing_connections(other, uid)
    try:
        assert store.customer_id(conn, tid) is None
        with conn.cursor() as cur:
            with pytest.raises(psycopg2.Error) as error:
                cur.execute(
                    "INSERT INTO billing_customers(tenant_id,stripe_customer_id) VALUES(%s,'cus_forged')",
                    (tid,),
                )
            assert error.value.pgcode == "42501"
    finally:
        conn.rollback()
        conn.close()
        with owner_db.cursor() as cur:
            cur.execute("DELETE FROM companies WHERE tenant_id=%s", (other,))
    conn = billing_connections(tid, uid)
    try:
        assert store.customer_id(conn, tid) == "cus_test_" + tid
    finally:
        conn.rollback()
        conn.close()


def test_concurrent_delivery_claims_one_execution(owner_db, tenant, monkeypatch):
    if os.getenv("BILLING_TEST_ENGINE") == "pglite":
        pytest.skip(
            "Native PostgreSQL multi-session concurrency required; PGlite multiplexing is not equivalent"
        )
    import psycopg2

    from scripts.billing_verification import validate_test_environment

    tid, _ = tenant
    eid = "evt_test_" + uuid.uuid4().hex
    event = {
        "id": eid,
        "type": "customer.subscription.updated",
        "created": int(time.time()),
        "data": {"object": {"id": "sub_test_race"}},
        "livemode": False,
    }
    calls = []
    results = []
    errors = []

    def synchronize(conn, sid, created, hint=None):
        calls.append(sid)
        time.sleep(0.15)
        return tid

    monkeypatch.setattr(webhooks, "sync_subscription", synchronize)

    def run():
        conn = psycopg2.connect(
            validate_test_environment(dict(os.environ), database=True),
            gssencmode="disable",
        )
        try:
            results.append(webhooks.handle_event(conn, event)["duplicate"])
        except Exception as error:  # noqa: BLE001 - report worker failures to the parent test
            errors.append(type(error).__name__)
        finally:
            conn.close()

    threads = [threading.Thread(target=run) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not any(thread.is_alive() for thread in threads)
    assert not errors
    assert len(calls) == 1 and sorted(results) == [False, True, True, True]


def test_existing_catalog_has_current_plan_records_without_reference_seeding(owner_db):
    rows = {p["plan_key"]: p for p in store.catalog(owner_db)}
    assert {k: rows[k]["name"]["en"] for k in ("starter", "growth", "enterprise")} == {
        "starter": "Standard",
        "growth": "Plus",
        "enterprise": "Pro",
    }
    assert {
        k: rows[k]["monthly_price"] for k in ("starter", "growth", "enterprise")
    } == {"starter": 55.0, "growth": 140.0, "enterprise": 350.0}
    assert rows["custom"]["self_serve"] is False
    for key in ("starter", "growth", "enterprise"):
        assert {p["period_code"] for p in rows[key]["prices"]} == {
            "monthly",
            "three-months",
            "six-months",
        }


def test_preflight_reads_schema_without_writes(owner_db):
    from scripts.billing_verification import preflight

    result = preflight(dict(os.environ))
    assert result["status"] == "PASS"
    assert result["databaseWrites"] is False and result["stripeCalls"] is False
    assert result["restrictedApplicationRole"] is True


def test_native_runtime_role_password_authentication(owner_db, tenant):
    if os.getenv("BILLING_TEST_ENGINE") == "pglite":
        pytest.skip(
            "PGlite socket authentication is not a native PostgreSQL password-authentication test"
        )
    from urllib.parse import urlsplit

    import psycopg2

    from scripts.billing_verification import validate_test_environment

    password = os.getenv("APP_DB_PASSWORD")
    assert password, (
        "APP_DB_PASSWORD must match ceopro_app in the isolated test cluster"
    )
    parsed = urlsplit(validate_test_environment(dict(os.environ), database=True))
    conn = psycopg2.connect(
        host=parsed.hostname,
        port=parsed.port,
        dbname=parsed.path.lstrip("/"),
        user="ceopro_app",
        password=password,
        gssencmode="disable",
        connect_timeout=5,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
            )
            assert cur.fetchone() == ("ceopro_app", False, False)
    finally:
        conn.close()


def test_late_failed_invoice_event_does_not_overwrite_a_paid_invoice(
    deliver, owner_db, tenant, test_price, monkeypatch
):
    """Release regression: stale invoice payload must not regress paid history.

    This exercises the current protected implementation. If it fails, do not
    hide it by accepting the incorrect state or changing production code here.
    """
    tid, _ = tenant
    _, price = test_price
    live = live_subscription(tid, price, status="active")
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda sid: live)
    invoice = {
        "id": "in_test_" + uuid.uuid4().hex,
        "object": "invoice",
        "subscription": live["id"],
        "customer": live["customer"],
        "amount_due": 5500,
        "amount_paid": 5500,
        "currency": "usd",
        "status": "paid",
    }
    monkeypatch.setattr(stripe_api, "retrieve_invoice", lambda iid: invoice)
    assert deliver("invoice.paid", invoice).status_code == 200
    stale = {**invoice, "status": "open", "amount_paid": 0}
    assert (
        deliver(
            "invoice.payment_failed", stale, created=int(time.time()) - 600
        ).status_code
        == 200
    )
    payment = store.payments(owner_db, tid)[0]
    assert payment["status"] == "succeeded", (
        "A delayed failure event overwrote confirmed paid invoice history; "
        "the protected main webhook/store needs a targeted correction."
    )

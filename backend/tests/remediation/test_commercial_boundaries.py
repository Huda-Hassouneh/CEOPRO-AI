import uuid
from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from src.ai.billing import store, stripe_api
from src.ai.core import usage
from tests.billing.test_database import live_subscription
from tests.integration_review.test_http_database import headers


def test_invoice_reconciliation_outage_retries_without_storing_failure(
    deliver, tenant, test_price, owner_db, monkeypatch
):
    tid, _ = tenant
    live = live_subscription(tid, test_price[1])
    invoice = {
        "id": "in_test_" + uuid.uuid4().hex,
        "subscription": live["id"],
        "customer": live["customer"],
        "status": "paid",
        "amount_paid": 5500,
        "amount_due": 5500,
        "currency": "usd",
    }
    eid = "evt_test_" + uuid.uuid4().hex
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda sid: live)

    def unavailable(iid):
        raise RuntimeError("Test invoice outage")

    monkeypatch.setattr(stripe_api, "retrieve_invoice", unavailable)
    assert deliver("invoice.payment_failed", invoice, event_id=eid).status_code == 500
    assert store.payments(owner_db, tid) == []
    monkeypatch.setattr(stripe_api, "retrieve_invoice", lambda iid: invoice)
    assert deliver("invoice.payment_failed", invoice, event_id=eid).status_code == 200
    assert store.payments(owner_db, tid)[0]["status"] == "succeeded"
    assert (
        deliver("invoice.payment_failed", invoice, event_id=eid).json()["duplicate"]
        is True
    )


def test_invoice_customer_mismatch_rolls_back(
    deliver, tenant, other_tenant, test_price, owner_db, monkeypatch
):
    live = live_subscription(tenant[0], test_price[1])
    customer = "cus_test_other_" + other_tenant
    store.save_customer(owner_db, other_tenant, customer)
    invoice = {
        "id": "in_test_" + uuid.uuid4().hex,
        "subscription": live["id"],
        "customer": customer,
        "status": "paid",
        "amount_paid": 5500,
        "currency": "usd",
    }
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda sid: live)
    monkeypatch.setattr(stripe_api, "retrieve_invoice", lambda iid: invoice)
    assert deliver("invoice.paid", invoice).status_code == 500
    assert store.current_subscription(owner_db, tenant[0]) is None
    assert store.payments(owner_db, tenant[0]) == []
    assert store.payments(owner_db, other_tenant) == []


def test_provider_subscription_identity_mismatch_retries(
    deliver, tenant, test_price, owner_db, monkeypatch
):
    live = live_subscription(tenant[0], test_price[1])
    monkeypatch.setattr(
        stripe_api, "retrieve_subscription", lambda sid: {**live, "id": "sub_wrong"}
    )
    assert (
        deliver("customer.subscription.updated", {"id": live["id"]}).status_code == 500
    )
    assert store.current_subscription(owner_db, tenant[0]) is None


def test_paid_store_row_cannot_regress(owner_db, tenant):
    tid, _ = tenant
    invoice = {
        "id": "in_test_" + uuid.uuid4().hex,
        "amount_paid": 5500,
        "amount_due": 5500,
        "currency": "usd",
    }
    store.record_payment(owner_db, tid, invoice, None, "succeeded")
    store.record_payment(
        owner_db, tid, {**invoice, "amount_paid": 0}, None, "failed", "stale"
    )
    payment = store.payments(owner_db, tid)[0]
    assert payment["status"] == "succeeded" and payment["amount"] == 55
    assert payment["failure_reason"] is None


def test_report_different_parameters_cannot_share_a_free_key(
    client, assigned, billing_connections
):
    auth = headers(assigned, "bound-report-key")
    assert (
        client.get("/reports/sales/export?format=csv", headers=auth).status_code == 200
    )
    assert (
        client.get("/reports/sales/export?format=json", headers=auth).status_code == 409
    )


def test_removed_member_cannot_replay(client, assigned, billing_connections, owner_db):
    tid, uid = assigned
    auth = headers(assigned, "membership-report-key")
    assert (
        client.get("/reports/sales/export?format=csv", headers=auth).status_code == 200
    )
    with owner_db.cursor() as cur:
        cur.execute(
            "UPDATE tenant_users SET removed_at=NOW() WHERE tenant_id=%s AND user_id=%s",
            (tid, uid),
        )
    assert (
        client.get("/reports/sales/export?format=csv", headers=auth).status_code == 403
    )


def test_other_tenant_actor_cannot_reserve(assigned, other_tenant, billing_connections):
    with pytest.raises(HTTPException) as error:
        usage.reserve_request(
            other_tenant, usage.MONTHLY_REPORTS, "actor-key", assigned[1]
        )
    assert error.value.status_code == 403


def test_other_same_tenant_user_cannot_replay_internal_key(
    owner_db, assigned, billing_connections
):
    tid, uid = assigned
    other = str(uuid.uuid4())
    with owner_db.cursor() as cur:
        cur.execute(
            "INSERT INTO users(user_id,email,password_hash) VALUES(%s,%s,'not-a-login')",
            (other, f"test-{other}@example.test"),
        )
        cur.execute(
            "INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'staff')",
            (tid, other),
        )
    try:
        usage.reserve_request(tid, usage.MONTHLY_REPORTS, "shared-key", uid)
        with pytest.raises(HTTPException) as error:
            usage.reserve_request(tid, usage.MONTHLY_REPORTS, "shared-key", other)
        assert error.value.status_code == 409
    finally:
        with owner_db.cursor() as cur:
            cur.execute(
                "DELETE FROM tenant_users WHERE tenant_id=%s AND user_id=%s",
                (tid, other),
            )
            cur.execute("DELETE FROM users WHERE user_id=%s", (other,))


def test_refund_cannot_apply_twice_or_to_replacement(
    owner_db, assigned, billing_connections
):
    tid, uid = assigned
    first = usage.reserve_request(tid, usage.MONTHLY_REPORTS, "receipt-key", uid)
    usage.reserve_request(tid, usage.MONTHLY_REPORTS, "other-key", uid)
    usage.release_request(first)
    usage.release_request(first)
    replacement = usage.reserve_request(tid, usage.MONTHLY_REPORTS, "receipt-key", uid)
    assert replacement["request_id"] != first["request_id"]
    usage.release_request(first)
    with owner_db.cursor() as cur:
        cur.execute(
            "SELECT used FROM tenant_usage_counters WHERE tenant_id=%s AND feature_code='monthly_reports'",
            (tid,),
        )
        assert cur.fetchone()[0] == 2


def test_original_failure_cannot_refund_successful_replay(
    owner_db, assigned, billing_connections
):
    tid, uid = assigned
    receipt = usage.reserve_request(tid, usage.MONTHLY_REPORTS, "replay-key", uid)
    assert usage.reserve_request(tid, usage.MONTHLY_REPORTS, "replay-key", uid) is None
    usage.release_request(receipt)
    with owner_db.cursor() as cur:
        cur.execute(
            "SELECT used FROM tenant_usage_counters WHERE tenant_id=%s AND feature_code='monthly_reports'",
            (tid,),
        )
        assert cur.fetchone()[0] == 1


def test_period_scoped_release_preserves_old_history(
    owner_db, assigned, billing_connections
):
    tid, uid = assigned
    old = (date.today().replace(day=1) - timedelta(days=1)).replace(day=1)
    with owner_db.cursor() as cur:
        cur.execute(
            "INSERT INTO metered_request_keys(tenant_id,feature_code,idempotency_key,period_start,actor_user_id) VALUES(%s,'monthly_reports','period-key',%s,%s)",
            (tid, old, uid),
        )
    receipt = usage.reserve_request(tid, usage.MONTHLY_REPORTS, "period-key", uid)
    usage.release_request(receipt)
    with owner_db.cursor() as cur:
        cur.execute(
            "SELECT period_start FROM metered_request_keys WHERE tenant_id=%s AND idempotency_key='period-key'",
            (tid,),
        )
        assert cur.fetchall() == [(old,)]


def test_legacy_unbound_key_requires_new_key(
    client, owner_db, assigned, billing_connections
):
    tid, uid = assigned
    plan = usage.get_plan(owner_db, tid)
    with owner_db.cursor() as cur:
        cur.execute(
            "INSERT INTO metered_request_keys(tenant_id,feature_code,idempotency_key,period_start,actor_user_id) VALUES(%s,'monthly_reports',%s,%s,%s)",
            (tid, f"client:{uid}:legacy-key", plan["period_start"], uid),
        )
    assert (
        client.get(
            "/reports/sales/export?format=csv", headers=headers(assigned, "legacy-key")
        ).status_code
        == 409
    )


@pytest.mark.parametrize("amount", [True, False, float("inf"), float("nan")])
def test_invalid_quota_values_rejected(owner_db, assigned, amount):
    with pytest.raises(ValueError, match="positive integer"):
        usage.reserve(owner_db, assigned[0], usage.MONTHLY_REPORTS, amount)

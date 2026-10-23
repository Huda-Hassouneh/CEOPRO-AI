"""Negative paths and lifecycle transitions using unchanged HTTP routers + SQL.

Only Stripe's remote response boundary is doubled. No production data/model
outputs are seeded, and no assertion treats checkout redirect as activation.
"""

import os
import time
from datetime import UTC, datetime, timedelta

import pytest

from src.ai.billing import service, store, stripe_api
from src.ai.core import usage
from src.ai.core.security import create_access_token
from tests.billing.test_database import live_subscription


def headers(tenant, key=None):
    tid, uid = tenant
    result = {
        "Authorization": "Bearer "
        + create_access_token(tid, uid, email_verified=True)[0]
    }
    if key:
        result["Idempotency-Key"] = key
    return result


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", "/billing/checkout", {"plan_key": "growth"}),
        ("POST", "/billing/portal", None),
        ("POST", "/billing/change-plan", {"plan_key": "growth"}),
        ("DELETE", "/billing/scheduled-change", None),
        ("POST", "/billing/cancel", None),
        ("POST", "/billing/resume", None),
    ],
)
def test_all_billing_mutations_deny_staff_before_provider(
    client, owner_db, tenant, billing_connections, method, path, body
):
    if os.getenv("BILLING_TEST_ENGINE") == "pglite" and path in {
        "/billing/checkout",
        "/billing/change-plan",
        "/billing/scheduled-change",
    }:
        pytest.skip(
            "This mutation opens two DB connections; native PostgreSQL required"
        )
    tid, uid = tenant
    with owner_db.cursor() as cur:
        cur.execute(
            "UPDATE tenant_users SET role_key='staff' WHERE tenant_id=%s AND user_id=%s",
            (tid, uid),
        )
    result = client.request(method, path, json=body, headers=headers(tenant))
    assert result.status_code == 403, result.text


def test_removed_membership_cannot_read_invoices(
    client, owner_db, tenant, billing_connections
):
    tid, uid = tenant
    with owner_db.cursor() as cur:
        cur.execute(
            "UPDATE tenant_users SET removed_at=NOW() WHERE tenant_id=%s AND user_id=%s",
            (tid, uid),
        )
    assert client.get("/billing/invoices", headers=headers(tenant)).status_code == 403


def test_forged_cross_tenant_token_cannot_manage_billing(
    client, tenant, other_tenant, billing_connections
):
    assert (
        client.get(
            "/billing/invoices", headers=headers((other_tenant, tenant[1]))
        ).status_code
        == 403
    )


def test_report_http_retry_does_not_double_charge(
    client, assigned, billing_connections, owner_db
):
    auth = headers(assigned, "review-report-key")
    first = client.get("/reports/sales/export?format=csv", headers=auth)
    second = client.get("/reports/sales/export?format=csv", headers=auth)
    assert first.status_code == second.status_code == 200
    assert "attachment;" in first.headers["content-disposition"]
    with owner_db.cursor() as cur:
        cur.execute(
            "SELECT used FROM tenant_usage_counters WHERE tenant_id=%s AND feature_code='monthly_reports'",
            (assigned[0],),
        )
        assert cur.fetchone()[0] == 1


def test_report_http_old_key_cannot_bypass_cancelled_subscription(
    client, assigned, billing_connections, owner_db
):
    auth = headers(assigned, "review-report-key")
    assert (
        client.get("/reports/sales/export?format=csv", headers=auth).status_code == 200
    )
    with owner_db.cursor() as cur:
        cur.execute(
            "UPDATE tenant_plan_assignments SET status='cancelled' WHERE tenant_id=%s",
            (assigned[0],),
        )
    result = client.get("/reports/sales/export?format=csv", headers=auth)
    assert result.status_code == 402, (
        f"An inactive subscription exported again with HTTP {result.status_code}"
    )


def test_report_http_missing_subscription_is_denied(
    client, tenant, billing_connections
):
    result = client.get(
        "/reports/sales/export?format=csv", headers=headers(tenant, "review-no-plan")
    )
    assert result.status_code == 402
    assert result.json()["detail"]["reason"] == "SUBSCRIPTION_INACTIVE"


def test_report_http_new_key_cannot_bypass_exhausted_quota(
    client, assigned, billing_connections, owner_db
):
    tid, _ = assigned
    limit = usage.get_plan(owner_db, tid)["features"][usage.MONTHLY_REPORTS]["limit"]
    usage.reserve(owner_db, tid, usage.MONTHLY_REPORTS, limit)
    result = client.get(
        "/reports/sales/export?format=csv",
        headers=headers(assigned, "review-new-report"),
    )
    assert result.status_code == 402
    assert result.json()["detail"]["reason"] == "QUOTA_EXHAUSTED"


def test_late_old_subscription_cancellation_does_not_disable_new_subscription(
    deliver, tenant, test_price, owner_db, monkeypatch
):
    tid, _ = tenant
    _, price = test_price
    old = live_subscription(tid, price, status="canceled")
    new = live_subscription(tid, price)
    new["customer"] = old["customer"]
    provider = {old["id"]: old, new["id"]: new}
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda sid: provider[sid])
    assert (
        deliver("customer.subscription.deleted", {"id": old["id"]}).status_code == 200
    )
    assert (
        deliver("customer.subscription.created", {"id": new["id"]}).status_code == 200
    )
    assert (
        store.current_subscription(owner_db, tid)["stripe_subscription_id"] == new["id"]
    )
    assert (
        deliver(
            "customer.subscription.deleted",
            {"id": old["id"]},
            created=int(time.time()) - 600,
        ).status_code
        == 200
    )
    with owner_db.cursor() as cur:
        cur.execute(
            "SELECT status FROM tenant_plan_assignments WHERE tenant_id=%s", (tid,)
        )
        assert cur.fetchone()[0] == "active", (
            "A terminal event for an old subscription revoked the new active subscription"
        )


def test_renewal_moves_period_preserves_old_counter_history(
    deliver, tenant, test_price, owner_db, monkeypatch
):
    tid, _ = tenant
    _, price = test_price
    with owner_db.cursor() as cur:
        cur.execute(
            "INSERT INTO usage_plan_limits(plan_key,feature_code,limit_value) VALUES(%s,'monthly_reports',5)",
            (test_price[0],),
        )
    live = live_subscription(tid, price)
    now = datetime.now(UTC)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    previous = (start - timedelta(days=1)).replace(day=1)
    live["items"]["data"][0]["current_period_start"] = int(previous.timestamp())
    live["items"]["data"][0]["current_period_end"] = int(start.timestamp()) - 1
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda sid: live)
    assert (
        deliver("customer.subscription.updated", {"id": live["id"]}).status_code == 200
    )
    with owner_db.cursor() as cur:
        cur.execute(
            "INSERT INTO tenant_usage_counters(tenant_id,feature_code,period_start,used) VALUES(%s,'monthly_reports',%s,5)",
            (tid, previous.date()),
        )
    live["items"]["data"][0]["current_period_start"] = int(start.timestamp())
    live["items"]["data"][0]["current_period_end"] = int(
        (start + timedelta(days=35)).timestamp()
    )
    assert (
        deliver("customer.subscription.updated", {"id": live["id"]}).status_code == 200
    )
    reservation = usage.reserve(owner_db, tid, usage.MONTHLY_REPORTS)
    assert reservation["period_start"] == start.date()
    with owner_db.cursor() as cur:
        cur.execute(
            "SELECT used FROM tenant_usage_counters WHERE tenant_id=%s AND feature_code='monthly_reports' AND period_start=%s",
            (tid, previous.date()),
        )
        assert cur.fetchone()[0] == 5


@pytest.mark.parametrize("transport", ["service", "http"])
def test_upgrade_keeps_local_plan_until_webhook(
    client, deliver, tenant, test_price, higher_price, monkeypatch, owner_db, transport
):
    if transport == "http" and os.getenv("BILLING_TEST_ENGINE") == "pglite":
        pytest.skip(
            "HTTP plan changes hold two DB connections; native PostgreSQL required"
        )
    tid, _ = tenant
    low, low_price = test_price
    high, high_price = higher_price
    live = live_subscription(tid, low_price)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_offline")
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda sid: live)
    assert (
        deliver("customer.subscription.created", {"id": live["id"]}).status_code == 200
    )
    calls = []
    monkeypatch.setattr(
        stripe_api, "modify_subscription", lambda sid, **kw: calls.append(kw) or live
    )
    if transport == "http":
        result = client.post(
            "/billing/change-plan",
            headers=headers(tenant),
            json={"plan_key": high, "period_code": "monthly"},
        )
        assert result.status_code == 200, result.text
        data = result.json()
    else:
        data = service.change_plan(owner_db, owner_db, tid, high, "monthly")
    assert data["state"] == "applied"
    assert calls[0]["payment_behavior"] == "pending_if_incomplete"
    assert store.current_subscription(owner_db, tid)["plan_key"] == low
    live["items"]["data"][0]["price"]["id"] = high_price
    assert (
        deliver("customer.subscription.updated", {"id": live["id"]}).status_code == 200
    )
    assert store.current_subscription(owner_db, tid)["plan_key"] == high


@pytest.mark.parametrize("transport", ["service", "http"])
def test_downgrade_stages_then_webhook_applies(
    client, deliver, tenant, test_price, higher_price, monkeypatch, owner_db, transport
):
    if transport == "http" and os.getenv("BILLING_TEST_ENGINE") == "pglite":
        pytest.skip(
            "HTTP plan changes hold two DB connections; native PostgreSQL required"
        )
    tid, _ = tenant
    low, low_price = test_price
    high, high_price = higher_price
    live = live_subscription(tid, high_price)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_offline")
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda sid: live)
    assert (
        deliver("customer.subscription.created", {"id": live["id"]}).status_code == 200
    )
    now = int(time.time())
    phase = {
        "start_date": now - 86400,
        "end_date": now + 28 * 86400,
        "items": [{"price": high_price, "quantity": 1}],
    }
    monkeypatch.setattr(
        stripe_api,
        "create_schedule_from_subscription",
        lambda sid: {"id": "sched_test_review"},
    )
    monkeypatch.setattr(
        stripe_api,
        "retrieve_schedule",
        lambda sid: {"current_phase": phase, "phases": [phase]},
    )
    calls = []
    monkeypatch.setattr(
        stripe_api, "modify_schedule", lambda sid, **kw: calls.append(kw) or {}
    )
    if transport == "http":
        result = client.post(
            "/billing/change-plan",
            headers=headers(tenant),
            json={"plan_key": low, "period_code": "monthly"},
        )
        assert result.status_code == 200, result.text
        data = result.json()
    else:
        data = service.change_plan(owner_db, owner_db, tid, low, "monthly")
    assert data["state"] == "scheduled"
    current = store.current_subscription(owner_db, tid)
    assert current["plan_key"] == high and current["scheduled_plan_key"] == low
    assert calls[0]["phases"][1]["items"][0]["price"] == low_price
    live["items"]["data"][0]["price"]["id"] = low_price
    assert (
        deliver("customer.subscription.updated", {"id": live["id"]}).status_code == 200
    )
    current = store.current_subscription(owner_db, tid)
    assert current["plan_key"] == low and current["scheduled_plan_key"] is None


def test_actual_migration_runner_repeat_is_noop(
    owner_db, billing_connections, monkeypatch
):
    from pathlib import Path

    from scripts import apply_migrations

    expected = {p.name for p in Path(apply_migrations.MIGRATIONS_DIR).glob("*.sql")}
    with owner_db.cursor() as cur:
        cur.execute("SELECT filename FROM schema_migrations")
        assert {row[0] for row in cur.fetchall()} == expected
    # Production runner + real SQL connection; test role password sync is
    # disabled by the harness, not attempted against application credentials.
    from src.ai import db

    monkeypatch.delenv("APP_DB_PASSWORD", raising=False)
    conn = db.system_connection()
    try:
        assert apply_migrations.run(conn) == []
    finally:
        conn.close()

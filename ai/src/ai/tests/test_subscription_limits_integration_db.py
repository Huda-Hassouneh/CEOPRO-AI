"""
Subscription limits against a real Postgres: reports, team seats and products
(including concurrent requests), the trial lifecycle and its abuse rules,
Custom contracts (approval and audit), plan changes and cancellation
through a faked Stripe, webhook replay, and the migration's schema.
"""
import hashlib
import hmac
import json
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import psycopg2
import pytest

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")

from src.ai.billing import admin, service, store, stripe_api  # noqa: E402
from src.ai.core import entitlements, usage  # noqa: E402

PASSWORD = "Limits!Test-2026"


@pytest.fixture
def sys_conn():
    conn = psycopg2.connect(DATABASE_URL)
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from src.ai.main import app

    return TestClient(app)


def _sql(sql, params=()):
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall() if cursor.description else None
        conn.commit()
        return rows
    finally:
        conn.close()


def _company(conn, plan_key="starter", members=1) -> str:
    tenant = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, %s, 'JO', 'JOD');",
                       (tenant, f"Limits {tenant[:8]}"))
        cursor.execute("INSERT INTO tenant_plan_assignments (tenant_id, plan_key, status, source) VALUES (%s, %s, 'active', 'manual');",
                       (tenant, plan_key))
        for _ in range(members):
            cursor.execute("INSERT INTO users (user_id, email, password_hash, full_name) VALUES (%s, %s, 'x', 'M') RETURNING user_id;",
                           (str(uuid.uuid4()), f"m-{uuid.uuid4().hex[:10]}@example.com"))
            cursor.execute("INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, 'staff');",
                           (tenant, cursor.fetchone()[0]))
    conn.commit()
    return tenant


def _signed_up(client, plan_key="starter"):
    email = f"limits+{uuid.uuid4().hex[:8]}@example.com"
    session = client.post("/auth/signup", json={"full_name": "Owner", "business_name": "Limits Co", "email": email,
                                                 "country_code": "JO", "primary_currency": "JOD", "password": PASSWORD}).json()
    if plan_key:
        _sql("UPDATE tenant_plan_assignments SET plan_key = %s, status = 'active', source = 'manual' WHERE tenant_id = %s;",
             (plan_key, session["tenant_id"]))
        entitlements.forget(session["tenant_id"])
    return session, {"Authorization": f"Bearer {session['access_token']}"}


# --- reports -----------------------------------------------------------------------

def test_reports_stop_at_the_monthly_allowance_and_retries_are_not_counted(client):
    session, headers = _signed_up(client, "starter")       # Standard: 5 reports a month
    for n in range(5):
        response = client.get("/reports/sales/export", params={"format": "csv"},
                              headers={**headers, "Idempotency-Key": f"report-{n:04d}"})
        assert response.status_code == 200, response.text
    again = client.get("/reports/sales/export", params={"format": "csv"}, headers={**headers, "Idempotency-Key": "report-0000"})
    assert again.status_code == 200, "a retried report is the same report"
    over = client.get("/reports/sales/export", params={"format": "json"}, headers={**headers, "Idempotency-Key": "report-9999"})
    assert over.status_code == 402 and over.json()["detail"]["feature_code"] == "monthly_reports"
    subscription = client.get("/billing/subscription", headers=headers).json()
    assert subscription["usage"]["reports"] == 5 and subscription["limits"]["reports"] == 5


def test_concurrent_report_requests_cannot_exceed_the_allowance(sys_conn):
    tenant = _company(sys_conn, "starter")
    results = []

    def export(n):
        try:
            results.append(usage.reserve_request(tenant, usage.MONTHLY_REPORTS, f"k-{n}") is not None)
        except usage.PlanLimitReached:
            results.append(False)

    threads = [threading.Thread(target=export, args=(n,)) for n in range(15)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 5
    [(used,)] = _sql("SELECT used FROM tenant_usage_counters WHERE tenant_id = %s AND feature_code = 'monthly_reports';", (tenant,))
    assert used == 5


def test_a_failed_report_is_given_back(sys_conn):
    tenant = _company(sys_conn, "starter")
    counted = usage.reserve_request(tenant, usage.MONTHLY_REPORTS, "will-fail")
    usage.release_request(counted)
    [(used,)] = _sql("SELECT used FROM tenant_usage_counters WHERE tenant_id = %s AND feature_code = 'monthly_reports';", (tenant,))
    assert used == 0
    assert usage.reserve_request(tenant, usage.MONTHLY_REPORTS, "will-fail") is not None  # the retry counts once


# --- team seats --------------------------------------------------------------------

def test_invitations_stop_when_every_seat_is_taken_or_promised(client):
    _, headers = _signed_up(client, "starter")             # Standard: 5 seats, the owner uses one
    for n in range(4):
        invite = client.post("/settings/team/invitations", headers=headers,
                             json={"email": f"seat{n}-{uuid.uuid4().hex[:6]}@example.com", "role_key": "staff"})
        assert invite.status_code == 200, invite.text
    full = client.post("/settings/team/invitations", headers=headers,
                       json={"email": f"late-{uuid.uuid4().hex[:6]}@example.com", "role_key": "staff"})
    assert full.status_code == 402 and full.json()["detail"]["feature_code"] == "team_seats"


def test_concurrent_joins_cannot_take_more_seats_than_the_plan_has(sys_conn):
    tenant = _company(sys_conn, "starter", members=3)      # 3 of 5 seats used
    joiners = []
    with sys_conn.cursor() as cursor:
        for _ in range(10):
            cursor.execute("INSERT INTO users (user_id, email, password_hash, full_name) VALUES (%s, %s, 'x', 'J') RETURNING user_id;",
                           (str(uuid.uuid4()), f"j-{uuid.uuid4().hex[:10]}@example.com"))
            joiners.append(str(cursor.fetchone()[0]))
    sys_conn.commit()
    joined = []

    def join(user):
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT auth_join_tenant(%s, %s, 'staff', 5);", (tenant, user))
                joined.append(cursor.fetchone()[0])
            conn.commit()
        finally:
            conn.close()

    threads = [threading.Thread(target=join, args=(u,)) for u in joiners]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert joined.count(True) == 2
    [(members,)] = _sql("SELECT COUNT(*) FROM tenant_users WHERE tenant_id = %s AND removed_at IS NULL;", (tenant,))
    assert members == 5


# --- products ----------------------------------------------------------------------

def test_concurrent_product_creation_stops_at_the_limit(sys_conn):
    tenant = _company(sys_conn, "starter")                 # Standard: 100 products
    _sql("INSERT INTO products (tenant_id, product_name, current_price, currency, source) "
         "SELECT %s, jsonb_build_object('en', 'P' || n), 1, 'JOD', 'MANUAL' FROM generate_series(1, 98) AS n;", (tenant,))
    created = []

    def create(n):
        conn = psycopg2.connect(DATABASE_URL)
        try:
            usage.ensure_capacity(conn, tenant, usage.TRACKED_PRODUCTS)
            with conn.cursor() as cursor:
                cursor.execute("INSERT INTO products (tenant_id, product_name, current_price, currency, source) "
                               "VALUES (%s, jsonb_build_object('en', %s), 1, 'JOD', 'MANUAL');", (tenant, f"New {n}"))
            conn.commit()
            created.append(n)
        except usage.PlanLimitReached:
            conn.rollback()
        finally:
            conn.close()

    threads = [threading.Thread(target=create, args=(n,)) for n in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(created) == 2
    [(count,)] = _sql("SELECT COUNT(*) FROM products WHERE tenant_id = %s AND deleted_at IS NULL;", (tenant,))
    assert count == 100


def test_deleted_products_free_their_place(sys_conn):
    tenant = _company(sys_conn, "starter")
    _sql("INSERT INTO products (tenant_id, product_name, current_price, currency, source, deleted_at) "
         "SELECT %s, jsonb_build_object('en', 'Gone ' || n), 1, 'JOD', 'MANUAL', NOW() FROM generate_series(1, 150) AS n;", (tenant,))
    assert usage.capacity_left(sys_conn, tenant, usage.TRACKED_PRODUCTS) == 100


# --- trials ------------------------------------------------------------------------

def test_a_trial_ends_at_its_exact_utc_time(sys_conn):
    tenant = str(uuid.uuid4())
    with sys_conn.cursor() as cursor:
        cursor.execute("INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, 'T', 'JO', 'JOD');",
                       (tenant,))
    started = datetime(2026, 10, 1, 15, 30, tzinfo=timezone.utc)
    trial = store.start_trial(sys_conn, tenant, started, plan_key="enterprise")
    sys_conn.commit()
    assert trial["ends_at"] == started + timedelta(days=7)          # Pro: 7 days, to the second
    assert usage.get_plan(sys_conn, tenant, now=trial["ends_at"] - timedelta(seconds=1))["status"] == "trialing"
    assert usage.get_plan(sys_conn, tenant, now=trial["ends_at"])["status"] == "expired"


@pytest.mark.parametrize("plan_key, days", [("starter", 14), ("growth", 14), ("enterprise", 7)])
def test_trial_length_per_plan(sys_conn, plan_key, days):
    tenant = str(uuid.uuid4())
    with sys_conn.cursor() as cursor:
        cursor.execute("INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, 'T', 'JO', 'JOD');",
                       (tenant,))
    now = datetime.now(timezone.utc)
    assert store.start_trial(sys_conn, tenant, now, plan_key=plan_key)["ends_at"] == now + timedelta(days=days)
    sys_conn.rollback()


def test_one_trial_per_company_and_per_person(sys_conn):
    person = str(uuid.uuid4())
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    with sys_conn.cursor() as cursor:
        for tenant in (first, second):
            cursor.execute("INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, 'T', 'JO', 'JOD');",
                           (tenant,))
    assert store.start_trial(sys_conn, first, started_by_user_id=person) is not None
    assert store.start_trial(sys_conn, first, started_by_user_id=person) is None
    assert store.trial_eligibility(sys_conn, second, "growth", person) == "trial_already_used_by_person"
    assert store.start_trial(sys_conn, second, started_by_user_id=person) is None
    assert store.trial_eligibility(sys_conn, second, "custom", None) == "plan_has_no_trial"
    sys_conn.rollback()


def test_the_trial_endpoint_refuses_a_second_trial(client):
    _, headers = _signed_up(client, None)                  # sign-up already started the Plus trial
    again = client.post("/billing/trial", headers=headers, json={"plan_key": "enterprise"})
    assert again.status_code == 409 and again.json()["detail"]["reason"] == "trial_already_used"


def test_a_company_without_a_plan_has_no_access(sys_conn, monkeypatch):
    monkeypatch.setenv("UNASSIGNED_PLAN_ACCESS", "none")
    tenant = str(uuid.uuid4())
    with sys_conn.cursor() as cursor:
        cursor.execute("INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, 'T', 'JO', 'JOD');",
                       (tenant,))
    plan = usage.get_plan(sys_conn, tenant)
    assert plan["status"] == "none" and plan["status"] not in usage.ACCESS_GRANTING_STATUSES
    sys_conn.rollback()


# --- Custom contracts --------------------------------------------------------------

def test_a_custom_contract_needs_approval_details_and_is_audited(sys_conn):
    tenant = _company(sys_conn, "starter")
    with pytest.raises(admin.AdminError):
        admin.set_custom_contract(sys_conn, tenant_id=tenant, contract_ref="C-1", approved_by="", reason="x",
                                  limits={"ai_credits": 5000})
    with pytest.raises(admin.AdminError):
        admin.set_custom_contract(sys_conn, tenant_id=tenant, contract_ref="C-1", approved_by="Ops", reason="x",
                                  limits={"made_up_feature": 1})
    sys_conn.rollback()
    admin.set_custom_contract(sys_conn, tenant_id=tenant, contract_ref="C-2026-7", approved_by="Finance lead",
                              reason="Signed order form", monthly_price=Decimal("900"), refresh_frequency="daily",
                              support_level="priority", limits={"tracked_products": 2000, "ai_credits": 9000,
                                                                "monthly_reports": 200, "team_seats": 75})
    sys_conn.commit()
    plan = usage.get_plan(sys_conn, tenant)
    limits = {code: f["limit"] for code, f in plan["features"].items()}
    assert plan["plan_key"] == "custom" and plan["status"] == "active"
    assert (limits["tracked_products"], limits["ai_credits"], limits["monthly_reports"], limits["team_seats"]) == (2000, 9000, 200, 75)
    assert limits["data_credits"] == 2780                  # not in the contract: Custom's finite default
    rows = _sql("SELECT action, subject, approved_by, contract_ref FROM entitlement_audit_log WHERE tenant_id = %s ORDER BY created_at;",
                (tenant,))
    assert ("set_contract", "C-2026-7", "Finance lead", "C-2026-7") in rows
    assert {r[1] for r in rows if r[0] == "set_limit"} == {"tracked_products", "ai_credits", "monthly_reports", "team_seats"}
    with pytest.raises(psycopg2.Error):
        _sql("UPDATE entitlement_audit_log SET approved_by = 'someone else' WHERE tenant_id = %s;", (tenant,))


def test_customers_cannot_buy_or_trial_a_custom_plan_online(client, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    _, headers = _signed_up(client, "starter")
    checkout = client.post("/billing/checkout", headers=headers, json={"plan_key": "custom", "period_code": "monthly"})
    assert checkout.status_code in (400, 404)
    assert client.post("/billing/trial", headers=headers, json={"plan_key": "custom"}).status_code == 409


# --- plan changes and cancellation (Stripe faked) ----------------------------------

@pytest.fixture
def stripe_prices(sys_conn):
    ids = {(p, "monthly"): f"price_{p}_{uuid.uuid4().hex[:6]}" for p in ("starter", "growth", "enterprise")}
    with sys_conn.cursor() as cursor:
        cursor.execute("SELECT plan_key, period_code, stripe_price_id FROM billing_plan_prices WHERE retired_at IS NULL;")
        original = cursor.fetchall()
        for (plan, period), sid in ids.items():
            cursor.execute("UPDATE billing_plan_prices SET stripe_price_id = %s WHERE plan_key = %s AND period_code = %s AND retired_at IS NULL;",
                           (sid, plan, period))
    sys_conn.commit()
    yield ids
    with sys_conn.cursor() as cursor:
        for plan, period, sid in original:
            cursor.execute("UPDATE billing_plan_prices SET stripe_price_id = %s WHERE plan_key = %s AND period_code = %s AND retired_at IS NULL;",
                           (sid, plan, period))
    sys_conn.commit()


def _subscribed(sys_conn, plan_key, stripe_prices):
    tenant = _company(sys_conn, plan_key)
    sub = {"id": f"sub_{uuid.uuid4().hex[:8]}", "customer": f"cus_{uuid.uuid4().hex[:8]}", "status": "active",
           "cancel_at_period_end": False, "canceled_at": None, "trial_end": None, "schedule": None, "metadata": {},
           "items": {"data": [{"id": "si_1", "price": {"id": stripe_prices[(plan_key, "monthly")]},
                               "current_period_start": int(time.time()), "current_period_end": int(time.time()) + 30 * 86400}]}}
    store.apply_subscription(sys_conn, tenant, sub, plan_key, "monthly", datetime.now(timezone.utc))
    sys_conn.commit()
    return tenant, sub


def test_an_upgrade_applies_now_and_invoices_the_difference(sys_conn, stripe_prices, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    tenant, sub = _subscribed(sys_conn, "starter", stripe_prices)
    calls = {}
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda sid: sub)
    monkeypatch.setattr(stripe_api, "modify_subscription", lambda sid, **kw: calls.setdefault("modify", kw) and {})
    result = service.change_plan(sys_conn, sys_conn, tenant, "growth", "monthly")
    assert result == {"state": "applied", "timing": "immediate"}
    assert calls["modify"]["proration_behavior"] == "always_invoice"
    assert calls["modify"]["items"][0]["price"] == stripe_prices[("growth", "monthly")]


def test_a_downgrade_waits_for_the_end_of_the_paid_period(sys_conn, stripe_prices, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    tenant, sub = _subscribed(sys_conn, "enterprise", stripe_prices)
    start, end = int(time.time()), int(time.time()) + 30 * 86400
    phase = {"start_date": start, "end_date": end, "items": [{"price": stripe_prices[("enterprise", "monthly")], "quantity": 1}]}
    modified = {}
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda sid: sub)
    monkeypatch.setattr(stripe_api, "create_schedule_from_subscription", lambda sid: {"id": "sched_1"})
    monkeypatch.setattr(stripe_api, "retrieve_schedule", lambda sid: {"current_phase": {"start_date": start, "end_date": end},
                                                                      "phases": [phase]})
    monkeypatch.setattr(stripe_api, "modify_schedule", lambda sid, **kw: modified.update(kw))
    result = service.change_plan(sys_conn, sys_conn, tenant, "starter", "monthly")
    assert result["state"] == "scheduled" and result["timing"] == "period_end"
    assert modified["phases"][1]["items"][0]["price"] == stripe_prices[("starter", "monthly")]
    assert usage.get_plan(sys_conn, tenant)["plan_key"] == "enterprise", "the paid plan stays until the period ends"


def test_cancelling_keeps_access_until_the_period_ends(sys_conn, stripe_prices, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    tenant, sub = _subscribed(sys_conn, "growth", stripe_prices)
    sent = {}
    monkeypatch.setattr(stripe_api, "retrieve_subscription", lambda sid: sub)
    monkeypatch.setattr(stripe_api, "modify_subscription", lambda sid, **kw: sent.update(kw) or {})
    result = service.set_cancellation(sys_conn, tenant, True)
    assert result["state"] == "cancelling" and sent == {"cancel_at_period_end": True}
    assert usage.get_plan(sys_conn, tenant)["status"] == "active"


# --- webhooks ----------------------------------------------------------------------

def test_a_replayed_webhook_with_an_old_signature_is_rejected(client, monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_replay_test")
    payload = json.dumps({"id": f"evt_{uuid.uuid4().hex}", "object": "event", "type": "ping", "created": int(time.time()),
                          "data": {"object": {}}, "livemode": False}).encode()
    old = int(time.time()) - 3600
    signature = hmac.new(b"whsec_replay_test", f"{old}.".encode() + payload, hashlib.sha256).hexdigest()
    response = client.post("/billing/webhook", content=payload, headers={"Stripe-Signature": f"t={old},v1={signature}"})
    assert response.status_code == 400


# --- the migration -----------------------------------------------------------------

def test_the_migration_left_the_expected_schema(sys_conn):
    with sys_conn.cursor() as cursor:
        for table in ("usage_ledger", "usage_ledger_adjustments", "tenant_credit_balances", "provider_cost_schedules",
                      "provider_spend_controls", "billing_cost_policy", "tenant_entitlement_overrides",
                      "tenant_custom_contracts", "entitlement_audit_log", "metered_request_keys"):
            cursor.execute("SELECT relrowsecurity OR relname IN ('provider_cost_schedules', 'provider_spend_controls', "
                           "'billing_cost_policy') FROM pg_class WHERE relname = %s;", (table,))
            assert cursor.fetchone() == (True,), table
        cursor.execute("SELECT pg_get_function_identity_arguments(oid) FROM pg_proc WHERE proname = 'auth_join_tenant';")
        assert [r[0] for r in cursor.fetchall()] == ["p_tenant_id uuid, p_user_id uuid, p_role_key character varying, p_seat_limit bigint"]
        cursor.execute("SELECT top_ups_enabled, ai_fallback_policy, target_contribution_margin FROM billing_cost_policy;")
        assert cursor.fetchone() == (False, "none", Decimal("0.7000"))
        cursor.execute("SELECT COUNT(*) FROM provider_cost_schedules WHERE provider IN ('google_places', 'apify', 'google_cse') "
                       "AND unit_cost_usd IS NOT NULL;")
        assert cursor.fetchone()[0] == 0, "paid provider prices are never invented"
        with pytest.raises(psycopg2.Error):
            cursor.execute("UPDATE billing_cost_policy SET top_ups_enabled = TRUE;")
    sys_conn.rollback()

"""Native SQL tests for the separate setup identity; Stripe is always offline.

SET SESSION AUTHORIZATION tests privileges across rollback; the host proof separately
exercises password authentication. No role passwords or memberships are changed.
"""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import os
import uuid

import psycopg2
import pytest

from src.ai import db
from src.ai.billing import checkout_attempts, service, store, stripe_api
from src.ai.core.security import TenantContext


@pytest.fixture
def setup_connections(owner_db):
    def scoped(tid, uid):
        raw = psycopg2.connect(os.environ["BILLING_TEST_DATABASE_URL"])
        raw.autocommit = True
        with raw.cursor() as cur:
            cur.execute("SET SESSION AUTHORIZATION ceopro_billing_setup")
        raw.autocommit = False
        return db._BillingSetupConnection(db._UnpooledOwner(), raw, tid, uid)
    return scoped


def denied(conn, query, params=None):
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        with conn.cursor() as cur:
            cur.execute(query, params)
    conn.rollback()


def test_setup_role_has_no_admin_ownership_or_memberships(owner_db):
    with owner_db.cursor() as cur:
        for role in ("ceopro_billing_setup", "ceopro_trial_issuer"):
            cur.execute("SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolinherit,rolreplication,rolcanlogin FROM pg_roles WHERE rolname=%s", (role,))
            assert cur.fetchone() == (False, False, False, False, False, False, role == "ceopro_billing_setup")
            cur.execute("SELECT count(*) FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=%s)", (role,))
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT count(*) FROM pg_class WHERE relowner=(SELECT oid FROM pg_roles WHERE rolname=%s)", (role,))
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT has_schema_privilege(%s,'public','CREATE'),has_database_privilege(%s,current_database(),'CREATE')", (role, role))
            assert cur.fetchone() == (False, False)


@pytest.mark.parametrize("table", ["billing_subscriptions", "billing_payments", "billing_trials", "tenant_plan_assignments", "tenant_credit_balances"])
def test_setup_role_cannot_directly_grant_rights_or_write_ledgers(owner_db, table):
    with owner_db.cursor() as cur:
        cur.execute("SELECT has_table_privilege('ceopro_billing_setup',%s,'INSERT'),has_table_privilege('ceopro_billing_setup',%s,'UPDATE'),has_table_privilege('ceopro_billing_setup',%s,'DELETE')", (table, table, table))
        assert cur.fetchone() == (False, False, False)


def test_setup_attempts_and_customer_mapping_are_scoped_and_immutable(owner_db, tenant, setup_connections):
    tid, uid = tenant
    with closing(setup_connections(tid, uid)) as conn:
        attempt = checkout_attempts.reserve(conn, tid, "restricted-proof", "growth", "monthly")
        params = {"synthetic": "frozen"}
        assert checkout_attempts.freeze(conn, attempt, params) == params
        assert checkout_attempts.freeze(conn, attempt, {"tampered": True}) == params
        store.save_customer(conn, tid, "cus_offline_" + tid)
        conn.commit()
        checkout_attempts.opened(conn, attempt, {"id": "cs_offline_" + tid})
        denied(conn, "UPDATE billing_checkout_attempts SET request_key='tampered' WHERE attempt_id=%s", (attempt["attempt_id"],))
        denied(conn, "INSERT INTO billing_checkout_attempts(attempt_id,tenant_id,request_key,plan_key,period_code) VALUES(gen_random_uuid(),%s,'outside','growth','monthly')", (str(uuid.uuid4()),))
        denied(conn, "CREATE TABLE public.setup_forbidden(id int)")
        denied(conn, "SET ROLE ceopro_app")


def test_non_billing_member_is_denied_at_database(owner_db, tenant, setup_connections):
    tid, uid = tenant
    with owner_db.cursor() as cur:
        cur.execute("SELECT role_key FROM system_roles WHERE role_key NOT IN ('owner','admin','accountant') ORDER BY role_key LIMIT 1")
        role = cur.fetchone()[0]
        cur.execute("UPDATE tenant_users SET role_key=%s WHERE tenant_id=%s AND user_id=%s", (role, tid, uid))
    with closing(setup_connections(tid, uid)) as conn:
        denied(conn, "INSERT INTO billing_checkout_attempts(attempt_id,tenant_id,request_key,plan_key,period_code) VALUES(gen_random_uuid(),%s,'member','growth','monthly')", (tid,))
        denied(conn, "SELECT billing_setup_trial('growth',true)")
        with pytest.raises(psycopg2.errors.InvalidParameterValue):
            with conn.cursor() as cur:
                cur.execute("SELECT billing_setup_trial('growth',NULL)")
        conn.rollback()


def test_removed_principal_is_denied_at_database(owner_db, tenant, setup_connections):
    tid, uid = tenant
    with owner_db.cursor() as cur:
        cur.execute("UPDATE tenant_users SET platform_suspended_at=NOW() WHERE tenant_id=%s AND user_id=%s", (tid, uid))
    with closing(setup_connections(tid, uid)) as conn:
        denied(conn, "INSERT INTO billing_checkout_attempts(attempt_id,tenant_id,request_key,plan_key,period_code) VALUES(gen_random_uuid(),%s,'suspended','growth','monthly')", (tid,))
        denied(conn, "SELECT billing_setup_trial('growth',true)")


def test_trial_command_preserves_one_time_rule_and_snapshot(owner_db, tenant, setup_connections):
    tid, uid = tenant
    with closing(setup_connections(tid, uid)) as conn:
        assert store.trial_eligibility(conn, tid, "growth", uid) is None
        trial = store.start_trial(conn, tid, started_by_user_id=uid, plan_key="growth")
        conn.commit()
        assert trial["ends_at"] - trial["started_at"] == timedelta(days=14)
        assert store.trial_eligibility(conn, tid, "growth", uid) == "trial_already_used"
        assert store.start_trial(conn, tid, started_by_user_id=uid, plan_key="growth") is None
        denied(conn, "UPDATE tenant_plan_assignments SET status='active' WHERE tenant_id=%s", (tid,))
        with pytest.raises(ValueError, match="identity"):
            store.trial_eligibility(conn, str(uuid.uuid4()), "growth", uid)
        with pytest.raises(ValueError, match="database time"):
            store.start_trial(conn, tid, datetime.now(), started_by_user_id=uid)
    with owner_db.cursor() as cur:
        cur.execute("SELECT status,source,catalog_snapshot IS NOT NULL FROM tenant_plan_assignments WHERE tenant_id=%s", (tid,))
        assert cur.fetchone() == ("trialing", "trial", True)


def test_same_person_trial_in_other_tenant_is_denied_without_exposing_rows(owner_db, tenant, setup_connections):
    tid, uid = tenant
    other = str(uuid.uuid4())
    try:
        with closing(setup_connections(tid, uid)) as conn:
            assert store.start_trial(conn, tid, started_by_user_id=uid)
            conn.commit()
        with owner_db.cursor() as cur:
            cur.execute("INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,'Synthetic second workspace','US','USD')", (other,))
            cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')", (other, uid))
        with closing(setup_connections(other, uid)) as conn:
            assert store.trial_eligibility(conn, other, "growth", uid) == "trial_already_used_by_person"
            assert store.start_trial(conn, other, started_by_user_id=uid) is None
            denied(conn, "SELECT * FROM billing_trials")
    finally:
        with owner_db.cursor() as cur:
            cur.execute("DELETE FROM companies WHERE tenant_id=%s", (other,))


def test_two_concurrent_trial_requests_issue_one_assignment(owner_db, tenant, setup_connections):
    tid, uid = tenant
    def claim():
        with closing(setup_connections(tid, uid)) as conn:
            result = store.start_trial(conn, tid, started_by_user_id=uid)
            conn.commit()
            return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))
    assert sum(result is not None for result in results) == 1
    with owner_db.cursor() as cur:
        cur.execute("SELECT count(*) FROM tenant_plan_assignments WHERE tenant_id=%s", (tid,))
        assert cur.fetchone()[0] == 1


def test_actual_checkout_http_uses_setup_role_and_persists_no_paid_rights(client, owner_db, tenant, test_price, billing_connections, setup_connections, monkeypatch):
    from src.ai.routers import billing
    tid, uid = tenant
    plan, _ = test_price
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_offline")
    monkeypatch.setenv("PUBLIC_FRONTEND_ORIGIN", "http://127.0.0.1:15273")
    monkeypatch.setattr(db, "billing_setup_connection", setup_connections)
    client.app.dependency_overrides[billing.get_tenant_context] = lambda: TenantContext(tid, uid)
    monkeypatch.setattr(stripe_api, "create_customer", lambda *a, **kw: {"id": "cus_setup_" + tid})
    calls = []
    def create(params, idempotency_key):
        calls.append(idempotency_key)
        return {"id": "cs_setup_" + tid, "url": "https://checkout.stripe.test/offline"}
    monkeypatch.setattr(stripe_api, "create_checkout_session", create)
    monkeypatch.setattr(stripe_api, "retrieve_checkout_session", lambda sid: {"id": sid, "url": "https://checkout.stripe.test/offline", "status": "open"})
    for _ in range(2):
        response = client.post("/billing/checkout", json={"plan_key": plan, "period_code": "monthly"})
        assert response.status_code == 200, response.json()
    assert len(calls) == 1
    with owner_db.cursor() as cur:
        cur.execute("SELECT count(*) FROM billing_checkout_attempts WHERE tenant_id=%s AND state='open'", (tid,))
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT count(*) FROM billing_subscriptions WHERE tenant_id=%s", (tid,))
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM tenant_plan_assignments WHERE tenant_id=%s", (tid,))
        assert cur.fetchone()[0] == 0


def test_actual_trial_http_uses_execute_only_issuer(client, tenant, billing_connections, setup_connections, monkeypatch):
    from src.ai.routers import billing
    tid, uid = tenant
    monkeypatch.setattr(db, "billing_setup_connection", setup_connections)
    client.app.dependency_overrides[billing.get_tenant_context] = lambda: TenantContext(tid, uid)
    response = client.post("/billing/trial", json={"plan_key": "growth"})
    assert response.status_code == 200, response.json()
    response = client.post("/billing/trial", json={"plan_key": "growth"})
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "trial_already_used"


def test_managed_promotion_setup_persists_audit_but_cannot_settle(owner_db, tenant, test_price, setup_connections, billing_connections, monkeypatch):
    import json
    from src.ai.billing import promotions
    tid, uid = tenant
    plan, _ = test_price
    pid = str(uuid.uuid4())
    code = "SETUP_" + uuid.uuid4().hex[:12].upper()
    terms = {"discount_type": "percent", "discount_value": 100, "currency": "USD",
             "starts_at": None, "expires_at": None, "max_uses": 1, "max_uses_per_tenant": 1,
             "invoice_scope": "initial_subscription", "stripe_coupon_id": "coupon_offline_" + pid,
             "stripe_promotion_code_id": "promo_offline_" + pid}
    monkeypatch.setenv("KEEL_MANAGED_PROMOTIONS_ENABLED", "true")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_offline")
    monkeypatch.setenv("PUBLIC_FRONTEND_ORIGIN", "http://127.0.0.1:15273")
    try:
        with owner_db.cursor() as cur:
            cur.execute("INSERT INTO billing_promotions(promotion_id,code,name,status,terms,stripe_coupon_id,stripe_promotion_code_id,approval_reference,approved_by,approved_at) VALUES(%s,%s,'Synthetic offline only','active',%s::jsonb,%s,%s,'disposable regression only',%s,NOW())", (pid, code, json.dumps(terms), terms["stripe_coupon_id"], terms["stripe_promotion_code_id"], uid))
            cur.execute("INSERT INTO billing_promotion_plans(promotion_id,plan_key) VALUES(%s,%s)", (pid, plan))
        monkeypatch.setattr(stripe_api, "create_customer", lambda *a, **kw: {"id": "cus_setup_promo_" + tid})
        monkeypatch.setattr(stripe_api, "create_checkout_session", lambda *a, **kw: {"id": "cs_setup_promo_" + tid, "url": "https://checkout.stripe.test/offline"})
        with closing(billing_connections(tid, uid)) as app, closing(setup_connections(tid, uid)) as setup:
            result = service.create_checkout(app, setup, tid, "synthetic@example.test", "Synthetic", plan, "monthly", code, uid)
            assert result["session_id"] == "cs_setup_promo_" + tid
            with setup.cursor() as cur:
                cur.execute("SELECT redemption_id,state,settled_at FROM billing_promotion_redemptions WHERE promotion_id=%s", (pid,))
                rid, state, settled = cur.fetchone()
                assert (state, settled) == ("pending", None)
                cur.execute("SELECT count(*) FROM billing_promotion_events WHERE redemption_id=%s", (rid,))
                assert cur.fetchone()[0] >= 3
                cur.execute("SELECT billing_promotion_capacity_reason(%s)", (pid,))
                assert cur.fetchone()[0] == "promotion_exhausted"
            denied(setup, "UPDATE billing_promotion_redemptions SET state='settled',settled_at=NOW(),stripe_subscription_id='sub_forged',stripe_initial_invoice_id='in_forged' WHERE redemption_id=%s", (rid,))
            denied(setup, "UPDATE billing_promotions SET terms='{}'::jsonb WHERE promotion_id=%s", (pid,))
            denied(setup, "INSERT INTO billing_promotion_events(tenant_id,redemption_id,event_type,new_state,stripe_event_id) VALUES(%s,%s,'forged_verified_payment','settled','evt_forged')", (tid, rid))
            promotions.provider_outcome_unknown(setup, tenant_id=tid, redemption_id=str(rid))
            setup.commit()
        with owner_db.cursor() as cur:
            cur.execute("SELECT state,settled_at FROM billing_promotion_redemptions WHERE promotion_id=%s", (pid,))
            assert cur.fetchone() == ("reconciliation_required", None)
    finally:
        with owner_db.cursor() as cur:
            cur.execute("DELETE FROM billing_promotion_redemptions WHERE promotion_id=%s", (pid,))
            cur.execute("DELETE FROM billing_promotion_plans WHERE promotion_id=%s", (pid,))
            cur.execute("DELETE FROM billing_promotions WHERE promotion_id=%s", (pid,))

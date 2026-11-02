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
from fastapi import HTTPException

from src.ai import db
from src.ai.billing import checkout_attempts, service, store, stripe_api
from src.ai.billing.stripe_gateway import StripeGateway
from src.ai.core.security import TenantContext
from .test_provider_trials import provider  # noqa: F401
from .test_reconciliation_roles import restricted_runtime, send  # noqa: F401


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


@pytest.mark.parametrize('days', [14, 7, 0])
def test_catalog_trial_days_flow_to_issued_cutoff_and_checkout(owner_db, tenant, test_price, setup_connections, billing_connections, monkeypatch, days):
    """Real DB/roles and domain/Stripe encoding, with an offline transport only."""
    tid, uid = tenant
    key, _ = test_price
    with owner_db.cursor() as cur:
        cur.execute('UPDATE usage_plans SET trial_days=%s WHERE plan_key=%s', (days,key))
    with closing(setup_connections(tid, uid)) as setup, closing(billing_connections(tid, uid)) as conn:
        issued = store.start_trial(owner_db, tid, started_by_user_id=uid, plan_key=key)
        assert next(p for p in store.catalog(conn) if p['plan_key'] == key)['trial_days'] == days
        if days:
            assert issued['ends_at'] - issued['started_at'] == timedelta(days=days)
            now = issued['started_at'].timestamp() + 60
        else:
            assert issued is None
            now = datetime.now().timestamp()
        monkeypatch.setattr(service.config, 'payments_enabled', lambda: True)
        monkeypatch.setattr(service.config, 'app_base_url', lambda: 'https://keel.example.test')
        monkeypatch.setattr(service.config, 'automatic_tax', lambda: False)
        monkeypatch.setattr(service, '_ensure_customer', lambda *a: 'cus_offline_duration')
        monkeypatch.setattr(service.time, 'time', lambda: now)
        monkeypatch.setattr(stripe_api, 'customer_clock_time', lambda *a, **kw: None)
        intents, requests = [], []

        class ObservedGateway(StripeGateway):
            def prepare_checkout(self, intent):
                intents.append(intent)
                return super().prepare_checkout(intent)

        monkeypatch.setattr(service, 'payment_gateway', ObservedGateway)
        def send(params, idempotency_key):
            requests.append(params)
            return {'id': 'cs_offline_duration', 'status': 'open', 'url': 'https://payments.example.test'}
        monkeypatch.setattr(stripe_api, 'create_checkout_session', send)
        service._create_checkout(conn, setup, tid, 'synthetic@example.test', 'Synthetic', key, 'monthly')
        params = requests[0]['subscription_data']
        assert 'trial_period_days' not in params
        if days:
            assert intents[0].trial_end.timestamp() == int(issued['ends_at'].timestamp())
            assert params['trial_end'] == int(issued['ends_at'].timestamp())
            # The elapsed minute is consumed; it must never be added again.
            assert 0 < params['trial_end'] - now < days * 86400
            before = store.trial(conn, tid)
            with owner_db.cursor() as cur:
                cur.execute('UPDATE usage_plans SET trial_days=0 WHERE plan_key=%s', (key,))
            service._create_checkout(conn, setup, tid, 'synthetic@example.test', 'Synthetic', key, 'monthly')
            assert requests[-1]['subscription_data']['trial_end'] == params['trial_end']
            assert store.trial(conn, tid) == before
        else:
            assert intents[0].trial_end is None
            assert 'trial_end' not in params
            assert store.trial(conn, tid) is None


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
        denied(conn, "SELECT billing_setup_trial('growth',true)")
        trial = store.start_trial(owner_db, tid, started_by_user_id=uid, plan_key="growth")
        assert trial["ends_at"] - trial["started_at"] == timedelta(days=14)
        assert store.trial_eligibility(conn, tid, "growth", uid) == "trial_already_used"
        denied(conn, "SELECT billing_setup_trial('growth',true)")
        denied(conn, "UPDATE tenant_plan_assignments SET status='active' WHERE tenant_id=%s", (tid,))
        with pytest.raises(ValueError, match="identity"):
            store.trial_eligibility(conn, str(uuid.uuid4()), "growth", uid)
        with pytest.raises(ValueError, match="database time"):
            store.start_trial(conn, tid, datetime.now(), started_by_user_id=uid)
    with owner_db.cursor() as cur:
        cur.execute("SELECT status,source,catalog_snapshot IS NOT NULL FROM tenant_plan_assignments WHERE tenant_id=%s", (tid,))
        assert cur.fetchone() == ("trialing", "trial", True)


@pytest.mark.parametrize('plan_key,days', [('starter',14),('growth',14),('enterprise',7)])
def test_explicit_selected_trial_uses_catalog_snapshot_and_completes_onboarding(
    client, owner_db, tenant, setup_connections, billing_connections, monkeypatch, provider, send, plan_key, days,
):
    from src.ai import onboarding_profile as profile
    from src.ai.core import usage
    from src.ai.core.security import create_access_token
    tid, uid = tenant
    monkeypatch.setattr(db, 'billing_setup_connection', setup_connections)
    monkeypatch.setenv('UNASSIGNED_PLAN_ACCESS','none')
    # Availability must not depend on the legacy default-plan configuration.
    monkeypatch.setenv('TRIAL_PLAN_KEY', 'not-a-plan')
    token, _ = create_access_token(tid, uid, email_verified=True)
    headers = {'Authorization': 'Bearer ' + token}
    before = client.get('/billing/subscription', headers=headers).json()
    assert before['planId'] is None and before['planName'] is None
    assert not before['assigned'] and not before['hasAccess'] and not before['trialUsed']
    assert {'starter','growth','enterprise'} <= set(before['trialEligiblePlanIds'])
    with closing(billing_connections(tid, uid)) as conn:
        choices = [dict(country='JO',city='amman',language='en'),dict(industry='retail'),
                   dict(businessSize='1-50',annualRevenue='under-100k'),dict(objectives=['knowledge']),
                   dict(selectedPlan=plan_key,billingPeriod='monthly')]
        for number, values in enumerate(choices,1):
            profile.save(conn,tid,uid,profile.StepRequest(step=number,expected_revision=number-1,**values))
        conn.commit()
        with pytest.raises(HTTPException) as blocked:
            profile.complete(conn,tid,uid)
        assert blocked.value.status_code == 409
        conn.rollback()
    response = client.post('/billing/trial', headers=headers, json={'plan_key':plan_key})
    assert response.status_code == 200, response.text
    assert not client.get('/billing/subscription',headers=headers).json()['hasAccess']
    sub = provider['confirm'](response.json()['session_id'])
    assert send('customer.subscription.created',sub).status_code == 200
    with owner_db.cursor() as cur:
        cur.execute('SELECT plan_key,ends_at-started_at FROM billing_trials WHERE tenant_id=%s',(tid,))
        assert cur.fetchone() == (plan_key,timedelta(days=days))
        cur.execute('SELECT plan_key,status,source,catalog_snapshot FROM tenant_plan_assignments WHERE tenant_id=%s',(tid,))
        assigned, status, source, snapshot = cur.fetchone()
        assert (assigned,status,source) == (plan_key,'trialing','stripe')
        assert snapshot['plan_key'] == plan_key
        cur.execute('SELECT feature_code FROM usage_plan_entitlements WHERE plan_key=%s ORDER BY feature_code',(plan_key,))
        assert snapshot['entitlements'] == [row[0] for row in cur.fetchall()]
        cur.execute('SELECT feature_code,limit_value,trial_limit_value FROM usage_plan_limits WHERE plan_key=%s',(plan_key,))
        expected_limits = {code: trial if trial is not None else limit for code,limit,trial in cur.fetchall()}
    with closing(billing_connections(tid,uid)) as conn:
        effective = usage.get_plan(conn,tid)
        assert {code:item['limit'] for code,item in effective['features'].items()} == expected_limits
        assert profile.complete(conn,tid,uid)['isComplete']
        conn.commit()
        original_trial = store.trial(conn,tid)
    # A different selected plan cannot replace or extend this issued trial.
    duplicate = client.post('/billing/trial',headers=headers,json={'plan_key':'growth' if plan_key!='growth' else 'enterprise'})
    assert duplicate.status_code == 409
    with closing(billing_connections(tid,uid)) as conn:
        assert store.trial(conn,tid) == original_trial
        assert usage.get_plan(conn,tid)['plan_key'] == plan_key
    after = client.get('/billing/subscription',headers=headers).json()
    assert after['trialEligiblePlanIds'] == [] and not after['trialAvailable']


def test_zero_day_plan_is_not_offered_or_issued(client, owner_db, tenant, test_price, setup_connections, billing_connections, monkeypatch, provider):
    from src.ai.core.security import create_access_token
    tid,uid = tenant
    key,_ = test_price  # An active private fixture with trial_days=0.
    monkeypatch.setattr(db,'billing_setup_connection',setup_connections)
    token,_ = create_access_token(tid,uid,email_verified=True)
    headers = {'Authorization':'Bearer '+token}
    available = client.get('/billing/subscription',headers=headers).json()
    assert key not in available['trialEligiblePlanIds']
    denied_trial = client.post('/billing/trial',headers=headers,json={'plan_key':key})
    assert denied_trial.status_code == 409
    assert denied_trial.json()['detail']['reason'] == 'plan_has_no_trial'
    with owner_db.cursor() as cur:
        for table in ('billing_trials','tenant_plan_assignments'):
            cur.execute('SELECT count(*) FROM '+table+' WHERE tenant_id=%s',(tid,))
            assert cur.fetchone()[0] == 0


def test_same_person_trial_in_other_tenant_is_denied_without_exposing_rows(owner_db, tenant, setup_connections):
    tid, uid = tenant
    other = str(uuid.uuid4())
    try:
        assert store.start_trial(owner_db, tid, started_by_user_id=uid)
        with owner_db.cursor() as cur:
            cur.execute("INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,'Synthetic second workspace','US','USD')", (other,))
            cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')", (other, uid))
        with closing(setup_connections(other, uid)) as conn:
            assert store.trial_eligibility(conn, other, "growth", uid) == "trial_already_used_by_person"
            denied(conn, "SELECT billing_setup_trial('growth',true)")
            denied(conn, "SELECT * FROM billing_trials")
    finally:
        with owner_db.cursor() as cur:
            cur.execute("DELETE FROM companies WHERE tenant_id=%s", (other,))


def test_two_concurrent_trial_requests_cannot_issue_cardless_assignment(owner_db, tenant, setup_connections):
    tid, uid = tenant
    def claim(plan_key):
        with closing(setup_connections(tid, uid)) as conn:
            denied(conn, 'SELECT billing_setup_trial(%s,true)', (plan_key,))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ['starter','enterprise']))
    assert results == [None,None]
    with owner_db.cursor() as cur:
        cur.execute("SELECT count(*) FROM tenant_plan_assignments WHERE tenant_id=%s", (tid,))
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM billing_trials WHERE tenant_id=%s", (tid,))
        assert cur.fetchone()[0] == 0


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


def test_actual_trial_http_uses_execute_only_issuer(client, tenant, billing_connections, setup_connections, monkeypatch, provider):
    from src.ai.routers import billing
    tid, uid = tenant
    monkeypatch.setattr(db, "billing_setup_connection", setup_connections)
    client.app.dependency_overrides[billing.get_tenant_context] = lambda: TenantContext(tid, uid)
    response = client.post("/billing/trial", json={"plan_key": "growth"})
    assert response.status_code == 200, response.json()
    again = client.post("/billing/trial", json={"plan_key": "growth"})
    assert again.status_code == 200 and again.json() == response.json()


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

"""The CI fixture follows public onboarding against native restricted PostgreSQL."""
import os
import uuid
from dataclasses import replace

import psycopg2
import pytest
from fastapi.testclient import TestClient

from scripts.ci_smoke_account import _complete_guided_onboarding, _verify_synthetic_account
from scripts.provider_trial_fixture import confirm_trial
from scripts.demo_companies.profiles import COMPANIES
from scripts.demo_companies.seed import Client, configure_company

pytestmark = pytest.mark.skipif(not os.getenv("AI_TEST_DATABASE_URL") or not os.getenv("APP_DB_PASSWORD"),
                                reason="Native PostgreSQL and restricted application credentials required")


@pytest.fixture(autouse=True)
def production_plan_access(monkeypatch):
    # The broad AI conftest enables legacy default access for old model fixtures.
    # These customer lifecycle tests must exercise the production policy instead.
    monkeypatch.setenv('UNASSIGNED_PLAN_ACCESS','none')


def test_verified_signup_and_new_workspace_have_no_commercial_records():
    from src.ai.main import app
    company = COMPANIES[0]
    client = Client('http://localhost')
    client.http.close()
    with TestClient(app,base_url='http://localhost') as http:
        client.http = http
        account = _verify_synthetic_account(client,company,f'no-auto-trial-{uuid.uuid4().hex}@keel-ci.example','Ci!Smoke-Only-2026')
        first = client.request('GET','/billing/subscription')
        assert first['planId'] is None and not first['assigned'] and not first['trialUsed']
        workspace = client.request('POST','/auth/workspaces',expected=(201,),json={'business_name':'Explicit plan required','country_code':'JO','primary_currency':'JOD'})
        client.headers = {'Authorization':'Bearer '+workspace['access_token']}
        second = client.request('GET','/billing/subscription')
        assert second['planId'] is None and not second['hasAccess'] and not second['trialUsed']
        assert set(first['trialEligiblePlanIds']) == set(second['trialEligiblePlanIds'])
        assert client.request('GET','/onboarding/state')['currentStep'] == 1
        with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as conn, conn.cursor() as cur:
            for tid in (account['tenant_id'],workspace['tenant_id']):
                for table in ('billing_trials','tenant_plan_assignments','billing_subscriptions','billing_customers'):
                    cur.execute('SELECT count(*) FROM '+table+' WHERE tenant_id=%s',(tid,))
                    assert cur.fetchone()[0] == 0, table
                cur.execute("SELECT count(*) FROM tenant_users WHERE tenant_id=%s AND role_key='owner'",(tid,))
                assert cur.fetchone()[0] == 1


def test_dashboard_api_requires_completed_onboarding_and_current_assignment(monkeypatch):
    from datetime import timedelta
    from src.ai.main import app
    from src.ai.billing import test_clock
    client = Client('http://localhost')
    client.http.close()
    with TestClient(app,base_url='http://localhost') as http:
        client.http = http
        account = _verify_synthetic_account(client,COMPANIES[0],f'dashboard-gate-{uuid.uuid4().hex}@keel-ci.example','Ci!Smoke-Only-2026')
        tid = account['tenant_id']
        denied = http.get('/dashboard/metrics',headers=client.headers)
        assert denied.status_code == 409 and denied.json()['detail']['reason'] == 'ONBOARDING_REQUIRED'
        # A historical/stale completion flag cannot authorize an unassigned company.
        with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as conn, conn.cursor() as cur:
            cur.execute('UPDATE companies SET onboarding_completed_at=now() WHERE tenant_id=%s',(tid,))
        denied = http.get('/dashboard/metrics',headers=client.headers)
        assert denied.status_code == 402 and denied.json()['detail']['reason'] == 'SUBSCRIPTION_INACTIVE'
        with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as conn, conn.cursor() as cur:
            cur.execute('UPDATE companies SET onboarding_completed_at=NULL WHERE tenant_id=%s',(tid,))
        confirm_trial(client,'enterprise')
        assert http.get('/dashboard/metrics',headers=client.headers).status_code == 409
        _complete_guided_onboarding(client,COMPANIES[0])
        assert client.request('GET','/onboarding/state')['selectedPlan'] == 'enterprise'
        assert http.get('/dashboard/metrics',headers=client.headers).status_code == 200
        with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as conn, conn.cursor() as cur:
            cur.execute('SELECT ends_at FROM billing_trials WHERE tenant_id=%s',(tid,))
            cutoff = cur.fetchone()[0]
        # Simulate observation after expiry without changing the issued trial.
        monkeypatch.setattr(test_clock,'tenant_now',lambda *a:cutoff+timedelta(seconds=1))
        denied = http.get('/dashboard/metrics',headers=client.headers)
        assert denied.status_code == 402 and denied.json()['detail']['reason'] == 'SUBSCRIPTION_INACTIVE'


def test_verified_ci_signup_saves_six_step_choices_and_retries_without_new_rights():
    from src.ai.main import app
    email = f"ci-smoke-{uuid.uuid4().hex}@keel-ci.example"
    company = replace(COMPANIES[0], products=COMPANIES[0].products[:10])
    client = Client("http://localhost")
    client.http.close()
    with TestClient(app, base_url="http://localhost") as http:
        client.http = http
        account = _verify_synthetic_account(client, company, email, "Ci!Smoke-Only-2026")
        assert account["created"] is True
        unassigned = client.request("GET", "/billing/subscription")
        assert unassigned["assigned"] is False and unassigned["hasAccess"] is False
        assert unassigned["planId"] is None and unassigned["trialUsed"] is False
        configure_company(client, company)
        before = http.post("/settings/company/onboarding/complete", headers=client.headers)
        assert before.status_code == 409
        assert before.json()["detail"] == "Complete your profile and choose a plan first."
        confirm_trial(client)
        _complete_guided_onboarding(client, company)
        state = client.request("GET", "/onboarding/state")
        subscription = client.request("GET", "/billing/subscription")
        assert state["isComplete"] and state["highestCompletedStep"] == 5 and state["revision"] == 5
        assert state["selectedPlan"] == subscription["planId"] == "growth"
        assert subscription["status"] == "trialing" and subscription["hasAccess"]
        assert subscription["hasSubscription"] is True
        assert http.get("/platform/me", headers=client.headers).status_code == 403
        assert http.put("/onboarding/state", json={"step": 1, "expected_revision": 0}).status_code == 401
        again = _verify_synthetic_account(client, company, email, "Ci!Smoke-Only-2026")
        assert again == {"tenant_id": account["tenant_id"], "created": False}
        _complete_guided_onboarding(client, company)
        assert client.request("GET", "/onboarding/state") == state
    with psycopg2.connect(os.environ["AI_TEST_DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM billing_trials WHERE tenant_id=%s", (account["tenant_id"],))
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT action_type,count(*) FROM audit_logs WHERE tenant_id=%s AND action_type IN ('ONBOARDING_STEP_SAVED','ONBOARDING_COMPLETED') GROUP BY action_type", (account["tenant_id"],))
        assert dict(cur.fetchall()) == {"ONBOARDING_STEP_SAVED": 5, "ONBOARDING_COMPLETED": 1}
        cur.execute("SELECT count(*) FROM billing_subscriptions WHERE tenant_id=%s", (account["tenant_id"],))
        assert cur.fetchone()[0] == 1


def test_independent_verified_accounts_keep_trials_onboarding_and_memberships_separate():
    """Public signup fixture, real restricted HTTP reads; no Stripe provider calls."""
    from src.ai.main import app
    from src.ai import db
    from contextlib import closing
    company = replace(COMPANIES[0], products=COMPANIES[0].products[:1])
    a, b = Client("http://localhost"), Client("http://localhost")
    a.http.close(); b.http.close()
    with TestClient(app, base_url="http://localhost") as http:
        a.http = b.http = http
        aid = _verify_synthetic_account(a, company, f"isolation-a-{uuid.uuid4().hex}@keel-ci.example", "Ci!Smoke-Only-2026")
        confirm_trial(a)
        _complete_guided_onboarding(a, company)
        product = a.request("POST", "/products", json={"product_name":{"en":"Private synthetic A product"},"current_price":1,"currency":"JOD","initial_stock_quantity":2})
        product_id = product["product_id"]
        bid = _verify_synthetic_account(b, company, f"isolation-b-{uuid.uuid4().hex}@keel-ci.example", "Ci!Smoke-Only-2026")
        assert aid["tenant_id"] != bid["tenant_id"]
        astate = a.request("GET", "/onboarding/state")
        bstate = b.request("GET", "/onboarding/state")
        assert astate["isComplete"] and not bstate["isComplete"]
        assert bstate["currentStep"] == 1 and bstate["highestCompletedStep"] == 0
        amembers = a.request("GET", "/auth/workspaces")["workspaces"]
        bmembers = b.request("GET", "/auth/workspaces")["workspaces"]
        assert {x["tenant_id"] for x in amembers} == {aid["tenant_id"]}
        assert {x["tenant_id"] for x in bmembers} == {bid["tenant_id"]}
        assert http.post("/auth/workspaces/switch", json={"tenant_id": aid["tenant_id"]}, headers=b.headers).status_code == 403
        for user in (a,b):
            sub = user.request("GET", "/billing/subscription")
            if user is a:
                assert sub["source"] == "stripe" and sub["status"] == "trialing"
            else:
                assert sub["source"] is None and sub["status"] == "none"
                assert not sub["assigned"] and not sub["trialUsed"] and not sub["hasAccess"]
            assert sub["hasSubscription"] is (user is a) and sub["hasBillingAccount"] is (user is a)
            assert http.get("/platform/me",headers=user.headers).status_code == 403
        assert http.post("/settings/company/onboarding/complete",headers=b.headers).status_code == 409
        assert http.get("/products/"+product_id,headers=b.headers).status_code == 404
        assert http.get("/products/"+product_id,headers=a.headers).status_code == 200
        bproducts = b.request("GET", "/products")
        assert product_id not in str(bproducts)
        assert b.request("GET", "/billing/invoices")["invoices"] == []
        assert b.request("GET", "/rag/documents")["documents"] == []
        assert http.get("/dashboard/metrics",headers=b.headers).status_code == 409
        assert http.get("/dashboard/inventory",headers=b.headers).status_code == 409
        # Caller-controlled tenant hints cannot change the authenticated company.
        company_b = b.request("GET", "/settings/company")
        other = http.get("/settings/company", params={"tenant_id":aid["tenant_id"]}, headers={**b.headers,"X-Tenant-ID":aid["tenant_id"]})
        assert other.status_code == 200 and other.json() == company_b
        # A signed token for a non-member tenant is still rejected by membership authority.
        from src.ai.core.security import create_access_token
        profile = b.request("GET", "/settings/profile")
        forged_scope, _ = create_access_token(aid["tenant_id"],profile["user_id"])
        assert http.get("/billing/subscription",headers={"Authorization":"Bearer "+forged_scope}).status_code == 403
        # Native restricted SQL boundaries also reject all foreign tenant rows.
        with closing(db.app_role_connection(bid["tenant_id"],profile["user_id"])) as conn, conn.cursor() as cur:
            for table in ("companies","products","inventory","tenant_plan_assignments","billing_customers","billing_subscriptions","tenant_credit_balances","usage_ledger","rag_documents_metadata"):
                cur.execute("SELECT count(*) FROM "+table+" WHERE tenant_id=%s",(aid["tenant_id"],))
                assert cur.fetchone()[0] == 0, table
    with psycopg2.connect(os.environ["AI_TEST_DATABASE_URL"]) as conn, conn.cursor() as cur:
        for tenant in (aid["tenant_id"],bid["tenant_id"]):
            expected_trials = 1 if tenant == aid["tenant_id"] else 0
            cur.execute("SELECT count(*) FROM billing_trials WHERE tenant_id=%s",(tenant,));assert cur.fetchone()[0] == expected_trials
            for table in ("billing_customers","billing_subscriptions","billing_checkout_attempts"):
                cur.execute("SELECT count(*) FROM "+table+" WHERE tenant_id=%s",(tenant,));assert cur.fetchone()[0] == expected_trials

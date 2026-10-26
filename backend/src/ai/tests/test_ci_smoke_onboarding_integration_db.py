"""The CI fixture follows public onboarding against native restricted PostgreSQL."""
import os
import uuid
from dataclasses import replace

import psycopg2
import pytest
from fastapi.testclient import TestClient

from scripts.ci_smoke_account import _complete_guided_onboarding, _verify_synthetic_account
from scripts.demo_companies.profiles import COMPANIES
from scripts.demo_companies.seed import Client, configure_company

pytestmark = pytest.mark.skipif(not os.getenv("AI_TEST_DATABASE_URL") or not os.getenv("APP_DB_PASSWORD"),
                                reason="Native PostgreSQL and restricted application credentials required")


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
        configure_company(client, company)
        before = http.post("/settings/company/onboarding/complete", headers=client.headers)
        assert before.status_code == 409
        assert before.json()["detail"] == "Complete your profile and choose a plan first."
        _complete_guided_onboarding(client, company)
        state = client.request("GET", "/onboarding/state")
        subscription = client.request("GET", "/billing/subscription")
        assert state["isComplete"] and state["highestCompletedStep"] == 5 and state["revision"] == 5
        assert state["selectedPlan"] == subscription["planId"] == "growth"
        assert subscription["status"] == "trialing" and subscription["hasAccess"]
        assert subscription["hasSubscription"] is False
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
        assert cur.fetchone()[0] == 0

"""A new trial is only offered when online payment can collect a payment method.

With provider-confirmed trials, a server without payments configured cannot
start one (POST /billing/trial -> 503 payments_not_configured), so the
subscription read must not advertise it; eligibility itself stays visible.
"""
import os
import uuid

import pytest
from fastapi.testclient import TestClient

from src.ai.tests.signup_helpers import create_verified_test_account

pytestmark = pytest.mark.skipif(not os.getenv("AI_TEST_DATABASE_URL") or not os.getenv("APP_DB_PASSWORD"),
                                reason="needs the disposable test database")


def test_no_trial_is_offered_without_online_payment(monkeypatch):
    from src.ai.billing import config
    from src.ai.main import app

    monkeypatch.setattr(config, "payments_enabled", lambda: False)
    monkeypatch.setenv("UNASSIGNED_PLAN_ACCESS", "none")  # the production default: no plan, no access
    client = TestClient(app)
    session = create_verified_test_account(client, {
        "full_name": "New owner", "business_name": "No Payments Co", "email": f"nopay+{uuid.uuid4().hex[:8]}@example.com",
        "country_code": "JO", "primary_currency": "JOD", "password": "NoPayments!2026"})
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    subscription = client.get("/billing/subscription", headers=headers).json()
    assert subscription["hasAccess"] is False and subscription["paymentsEnabled"] is False
    assert subscription["trialAvailable"] is False
    assert subscription["trialBlocker"] == "payments_not_configured"
    assert subscription["trialEligiblePlanIds"], "eligibility is still reported"
    refused = client.post("/billing/trial", headers=headers, json={"plan_key": subscription["trialEligiblePlanIds"][0], "period_code": "monthly"})
    assert refused.status_code == 503 and refused.json()["detail"]["reason"] == "payments_not_configured"

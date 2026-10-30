"""
One login, several companies, against the real database and the real
restricted app role: a signed-up owner creates a second company in another
industry, the new company starts empty and needs setup, switching between
them works only for companies the login belongs to, data never crosses,
and finishing setup is recorded.
"""
import os
import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient

from src.ai.tests.signup_helpers import create_verified_test_account

ADMIN_DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_DATABASE_URL or not os.getenv("APP_DB_PASSWORD"),
    reason="AI_TEST_DATABASE_URL and/or APP_DB_PASSWORD not set - skipping live-DB workspace test",
)
PASSWORD = "Workspace!Test2026"


@pytest.fixture
def client():
    from src.ai.main import app

    return TestClient(app)


def _signup(client, email, business, country="JO", currency="JOD"):
    return create_verified_test_account(client, {"full_name": "Owner", "business_name": business, "email": email,
                                                  "country_code": country, "primary_currency": currency, "password": PASSWORD})


def _auth(session):
    return {"Authorization": f"Bearer {session['access_token']}"}


def _cleanup(emails):
    admin = psycopg2.connect(ADMIN_DATABASE_URL)
    admin.autocommit = True
    with admin.cursor() as cursor:
        cursor.execute("SELECT tu.tenant_id FROM tenant_users tu JOIN users u ON u.user_id = tu.user_id WHERE u.email = ANY(%s);", (emails,))
        tenants = [r[0] for r in cursor.fetchall()]
        for table in ("products", "tenant_users", "billing_trials", "tenant_plan_assignments"):
            cursor.execute(f"DELETE FROM {table} WHERE tenant_id = ANY(%s::uuid[]);", (tenants,))
        cursor.execute("DELETE FROM companies WHERE tenant_id = ANY(%s::uuid[]);", (tenants,))
        cursor.execute("DELETE FROM users WHERE email = ANY(%s);", (emails,))
    admin.close()


def test_owner_runs_two_companies_in_different_industries_without_leakage(client):
    email = f"owner+{uuid.uuid4().hex[:8]}@example.com"
    other_email = f"other+{uuid.uuid4().hex[:8]}@example.com"
    try:
        restaurant = _signup(client, email, "Grill House")
        stranger = _signup(client, other_email, "Someone Else's Shop")

        company = client.get("/settings/company", headers=_auth(restaurant)).json()
        assert company["onboarding_completed_at"] is None and company["is_demo"] is False
        assert client.patch("/settings/company", headers=_auth(restaurant), json={"industry_key": "restaurant"}).status_code == 200
        product = client.post("/products", headers=_auth(restaurant), json={"product_name": {"en": "Mixed grill"}, "current_price": 7.5, "currency": "JOD"})
        assert product.status_code in (200, 201), product.text
        # Profile/plan acknowledgement is now durable; a direct completion bypass is refused.
        assert client.post("/settings/company/onboarding/complete", headers=_auth(restaurant)).status_code == 409
        choices = [dict(country="JO",city="amman",language="en"),dict(industry="restaurants"),
                   dict(businessSize="1-50",annualRevenue="under-100k"),dict(objectives=["forecasting"]),
                   dict(selectedPlan="growth",billingPeriod="monthly")]
        for revision, values in enumerate(choices):
            saved = client.put("/onboarding/state",headers=_auth(restaurant),json=dict(step=revision+1,expected_revision=revision,**values))
            assert saved.status_code == 200, saved.text
        done_response = client.post("/settings/company/onboarding/complete", headers=_auth(restaurant))
        assert done_response.status_code == 200, done_response.text
        assert done_response.json()["onboarding_completed_at"] is not None

        created = client.post("/auth/workspaces", headers=_auth(restaurant),
                              json={"business_name": "Shifa Pharmacy", "country_code": "AE", "primary_currency": "AED"})
        assert created.status_code == 201, created.text
        pharmacy = created.json()
        assert pharmacy["tenant_id"] != restaurant["tenant_id"] and pharmacy["role_key"] == "owner"

        new_company = client.get("/settings/company", headers=_auth(pharmacy)).json()
        assert new_company["business_name"] == "Shifa Pharmacy" and new_company["primary_currency"] == "AED"
        assert new_company["onboarding_completed_at"] is None and new_company["industry_key"] is None
        assert client.get("/products", headers=_auth(pharmacy)).json()["total"] == 0
        assert client.patch("/settings/company", headers=_auth(pharmacy), json={"industry_key": "pharmacy"}).status_code == 200
        status = client.get("/discovery/status", headers=_auth(pharmacy)).json()
        assert status["industry"]["key"] == "pharmacy"
        # One free trial per person: the owner's second company doesn't get another.
        second = client.get("/billing/subscription", headers=_auth(pharmacy)).json()
        assert second["status"] != "trialing" and second["trialUsed"] is False and second["trialAvailable"] is False

        listed = client.get("/auth/workspaces", headers=_auth(pharmacy)).json()
        assert {w["business_name"] for w in listed["workspaces"]} == {"Grill House", "Shifa Pharmacy"}

        # Logging in now asks which company to open.
        login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
        assert login.status_code == 409 and len(login.json()["detail"]["workspaces"]) == 2
        chosen = client.post("/auth/login", json={"email": email, "password": PASSWORD, "tenant_id": pharmacy["tenant_id"]})
        assert chosen.status_code == 200 and chosen.json()["tenant_id"] == pharmacy["tenant_id"]

        switched = client.post("/auth/workspaces/switch", headers=_auth(chosen.json()), json={"tenant_id": restaurant["tenant_id"]})
        assert switched.status_code == 200 and switched.json()["business_name"] == "Grill House"
        back = switched.json()
        assert client.get("/products", headers=_auth(back)).json()["total"] == 1
        assert client.get("/discovery/status", headers=_auth(back)).json()["industry"]["key"] == "restaurant"

        # A company this login doesn't belong to can't be opened.
        foreign = client.post("/auth/workspaces/switch", headers=_auth(back), json={"tenant_id": stranger["tenant_id"]})
        assert foreign.status_code == 403
        bad_login = client.post("/auth/login", json={"email": email, "password": PASSWORD, "tenant_id": stranger["tenant_id"]})
        assert bad_login.status_code == 403
    finally:
        _cleanup([email, other_email])


def test_creating_a_company_validates_input(client):
    email = f"owner+{uuid.uuid4().hex[:8]}@example.com"
    try:
        session = _signup(client, email, "First Co")
        assert client.post("/auth/workspaces", headers=_auth(session), json={"business_name": " ", "country_code": "JO", "primary_currency": "JOD"}).status_code == 422
        assert client.post("/auth/workspaces", headers=_auth(session), json={"business_name": "X", "country_code": "JOR", "primary_currency": "JOD"}).status_code == 422
        assert client.post("/auth/workspaces", json={"business_name": "X", "country_code": "JO", "primary_currency": "JOD"}).status_code == 401
    finally:
        _cleanup([email])

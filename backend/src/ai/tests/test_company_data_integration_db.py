"""
A company's data export and permanent deletion against the real database:
the export holds the company's records and none of its secrets; deletion
needs the owner and the typed company name, is refused while a paid
subscription runs, removes every record (including rows behind RESTRICT
foreign keys) and leaves other companies untouched.
"""
import io
import json
import os
import uuid
import zipfile

import psycopg2
import pytest
from fastapi.testclient import TestClient

from src.ai.tests.signup_helpers import create_verified_test_account

ADMIN_DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_DATABASE_URL or not os.getenv("APP_DB_PASSWORD"),
    reason="AI_TEST_DATABASE_URL and/or APP_DB_PASSWORD not set - skipping live-DB company data test",
)
PASSWORD = "CompanyData!Test2026"


@pytest.fixture
def client():
    from src.ai.main import app

    return TestClient(app)


def _signup(client, business):
    email = f"data+{uuid.uuid4().hex[:8]}@example.com"
    session = create_verified_test_account(client, {"full_name": "Owner", "business_name": business, "email": email,
                                                     "country_code": "JO", "primary_currency": "JOD", "password": PASSWORD})
    return {**session, "email": email}


def _auth(session):
    return {"Authorization": f"Bearer {session['access_token']}"}


def _admin(sql, params=()):
    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    conn.autocommit = True
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall() if cursor.description else None
    conn.close()
    return rows


def _sale(tenant_id, product_id):
    invoice_id = str(uuid.uuid4())
    _admin("INSERT INTO invoices (invoice_id, tenant_id, invoice_number, issue_date, currency, total_amount) VALUES (%s, %s, %s, NOW(), 'JOD', 9);",
           (invoice_id, tenant_id, f"INV-{invoice_id[:6]}"))
    _admin("INSERT INTO invoice_items (tenant_id, invoice_id, product_id, quantity, unit_price, total_price) VALUES (%s, %s, %s, 1, 9, 9);",
           (tenant_id, invoice_id, product_id))


def test_export_then_delete_a_company(client):
    owner = _signup(client, "Delete Me Bakery")
    other = _signup(client, "Keep Me Cafe")
    try:
        product = client.post("/products", headers=_auth(owner), json={"product_name": {"en": "Sourdough"}, "current_price": 9, "currency": "JOD"}).json()
        kept = client.post("/products", headers=_auth(other), json={"product_name": {"en": "Flat white"}, "current_price": 3, "currency": "JOD"}).json()
        _sale(owner["tenant_id"], product["product_id"])

        export = client.get("/settings/company/export", headers=_auth(owner))
        assert export.status_code == 200 and export.headers["content-type"] == "application/zip"
        archive = zipfile.ZipFile(io.BytesIO(export.content))
        names = archive.namelist()
        assert "data/products.jsonl" in names and "data/invoice_items.jsonl" in names and "team.json" in names
        products = [json.loads(line) for line in archive.read("data/products.jsonl").decode().splitlines()]
        assert [p["product_name"]["en"] for p in products] == ["Sourdough"]
        everything = b"".join(archive.read(n) for n in names)
        assert b"password_hash" not in everything and b"Flat white" not in everything
        assert json.loads(archive.read("team.json"))[0]["email"] == owner["email"]

        wrong = client.request("DELETE", "/settings/company", headers=_auth(owner), json={"confirm_name": "Something else"})
        assert wrong.status_code == 422

        _admin("""INSERT INTO billing_subscriptions (tenant_id, stripe_subscription_id, stripe_customer_id, plan_key, period_code, status)
                  VALUES (%s, %s, 'cus_x', 'pro', 'monthly', 'active');""", (owner["tenant_id"], f"sub_{uuid.uuid4().hex[:10]}"))
        blocked = client.request("DELETE", "/settings/company", headers=_auth(owner), json={"confirm_name": "Delete Me Bakery"})
        assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "SUBSCRIPTION_ACTIVE"
        _admin("UPDATE billing_subscriptions SET status = 'cancelled' WHERE tenant_id = %s;", (owner["tenant_id"],))

        deleted = client.request("DELETE", "/settings/company", headers=_auth(owner), json={"confirm_name": "  delete me bakery "})
        assert deleted.status_code == 200, deleted.text
        assert _admin("SELECT COUNT(*) FROM companies WHERE tenant_id = %s;", (owner["tenant_id"],))[0][0] == 0
        for table in ("products", "invoices", "invoice_items", "tenant_users", "billing_subscriptions"):
            assert _admin(f"SELECT COUNT(*) FROM {table} WHERE tenant_id = %s;", (owner["tenant_id"],))[0][0] == 0, table
        assert client.get("/settings/company", headers=_auth(owner)).status_code == 401  # session ended
        assert client.post("/auth/login", json={"email": owner["email"], "password": PASSWORD}).status_code == 403

        # The other company is untouched.
        assert client.get(f"/products/{kept['product_id']}", headers=_auth(other)).status_code == 200
    finally:
        for session in (owner, other):
            _admin("DELETE FROM invoice_items WHERE tenant_id = %s;", (session["tenant_id"],))
            _admin("DELETE FROM companies WHERE tenant_id = %s;", (session["tenant_id"],))
            _admin("DELETE FROM users WHERE email = %s;", (session["email"],))


def test_only_the_owner_can_delete_and_staff_cannot_export(client):
    owner = _signup(client, "Owner Only Co")
    try:
        staff_user = str(uuid.uuid4())
        _admin("INSERT INTO users (user_id, email, password_hash, full_name) VALUES (%s, %s, 'x', 'Staff');", (staff_user, f"staff+{staff_user[:8]}@example.com"))
        _admin("INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, 'staff');", (owner["tenant_id"], staff_user))
        from src.ai.core.security import create_access_token

        token, _ = create_access_token(tenant_id=owner["tenant_id"], user_id=staff_user)
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/settings/company/export", headers=headers).status_code == 403
        assert client.request("DELETE", "/settings/company", headers=headers, json={"confirm_name": "Owner Only Co"}).status_code == 403
        assert _admin("SELECT COUNT(*) FROM companies WHERE tenant_id = %s;", (owner["tenant_id"],))[0][0] == 1
    finally:
        _admin("DELETE FROM companies WHERE tenant_id = %s;", (owner["tenant_id"],))
        _admin("DELETE FROM users WHERE email = %s OR email LIKE 'staff+%%@example.com' AND full_name = 'Staff';", (owner["email"],))

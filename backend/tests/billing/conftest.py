"""Billing-only fixtures; load the unchanged production router, not AI models."""

import os
import uuid

import pytest
from scripts.billing_verification import is_test_database_name, validate_test_environment

# Do this before any protected billing/security module is imported.
validate_test_environment(
    dict(os.environ), database=os.getenv("BILLING_DATABASE_TESTS") == "1"
)
os.environ.setdefault("JWT_SECRET", "billing-isolated-test-secret-not-for-deployment")


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    """Offline provider doubles are explicit; genuine Stripe traffic is refused."""
    from src.ai.billing import stripe_api

    monkeypatch.setattr(
        stripe_api,
        "_client",
        lambda: pytest.fail("Unexpected real Stripe request in offline billing tests"),
    )
    # Redis revocation is substituted, not treated as verified infrastructure.
    from src.ai.core import security

    monkeypatch.setattr(security, "is_token_revoked", lambda token: False)


@pytest.fixture
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.ai.core.exceptions import register_exception_handlers
    from src.ai.routers.billing import router

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def owner_db():
    if os.getenv("BILLING_DATABASE_TESTS") != "1":
        pytest.skip("Database suite disabled; run the guarded runner with --database")
    import psycopg2

    url = validate_test_environment(dict(os.environ), database=True)
    conn = psycopg2.connect(
        url, connect_timeout=5, gssencmode="disable", sslmode="disable"
    )
    with conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        assert is_test_database_name(cur.fetchone()[0]), (
            "Refuse mismatched database"
        )
    conn.commit()
    conn.autocommit = True
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture
def tenant(owner_db):
    """Every test uses fresh IDs; teardown removes only this fixture's tenant."""
    tid, uid = str(uuid.uuid4()), str(uuid.uuid4())
    with owner_db.cursor() as cur:
        cur.execute(
            "INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,'Billing fixture','JO','JOD')",
            (tid,),
        )
        cur.execute(
            "INSERT INTO users(user_id,email,password_hash) VALUES(%s,%s,'not-a-login-password')",
            (uid, f"billing-{uid}@example.test"),
        )
        cur.execute(
            "INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')",
            (tid, uid),
        )
    owner_db.commit()
    yield tid, uid
    owner_db.rollback()
    with owner_db.cursor() as cur:
        cur.execute("DELETE FROM billing_webhook_events WHERE tenant_id=%s", (tid,))
        cur.execute("DELETE FROM companies WHERE tenant_id=%s", (tid,))
        cur.execute("DELETE FROM users WHERE user_id=%s", (uid,))
    owner_db.commit()


@pytest.fixture
def test_price(owner_db):
    """Private legacy-key fixture: never overwrite the nine public catalog rows."""
    key = "test_" + uuid.uuid4().hex[:18]
    sid = "price_test_" + uuid.uuid4().hex
    with owner_db.cursor() as cur:
        cur.execute(
            "INSERT INTO usage_plans(plan_key,display_name,display_name_ar,monthly_price,currency,trial_days,tier_level,self_serve,is_active) VALUES(%s,'Private test fixture','Private test fixture',55,'USD',0,1,TRUE,TRUE)",
            (key,),
        )
        cur.execute(
            "INSERT INTO billing_plan_prices(plan_key,period_code,interval_months,discount_percent,amount,currency,stripe_price_id) VALUES(%s,'monthly',1,0,55,'USD',%s)",
            (key, sid),
        )
    owner_db.commit()
    yield key, sid
    owner_db.rollback()
    with owner_db.cursor() as cur:
        cur.execute("DELETE FROM billing_subscriptions WHERE plan_key=%s", (key,))
        cur.execute("DELETE FROM tenant_plan_assignments WHERE plan_key=%s", (key,))
        cur.execute("DELETE FROM billing_plan_prices WHERE plan_key=%s", (key,))
        cur.execute("DELETE FROM usage_plans WHERE plan_key=%s", (key,))
    owner_db.commit()


@pytest.fixture
def billing_connections(monkeypatch, owner_db):
    """Production handlers use actual SQL and real SET ROLE, not fake repositories.

    Uses owner-authenticated test sockets then SET ROLE ceopro_app to exercise
    RLS. This verifies SQL privileges, not password authentication for that role.
    """
    import psycopg2
    from src.ai import db

    url = validate_test_environment(dict(os.environ), database=True)

    def system():
        return psycopg2.connect(
            url, connect_timeout=5, gssencmode="disable", sslmode="disable"
        )

    def scoped(tid, uid):
        # Existing wrapper reapplies LOCAL tenant context after every commit.
        from src.infrastructure.db_pool import PooledTenantConnection

        raw = system()
        raw.autocommit = True
        with raw.cursor() as cur:
            cur.execute("SET ROLE ceopro_app")
            cur.execute(
                "SELECT current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
            )
            assert cur.fetchone() == ("ceopro_app", False, False)
        raw.autocommit = False

        class SocketOwner:
            def putconn(self, connection, discard=False):
                try:
                    connection.rollback()
                    connection.autocommit = True
                    with connection.cursor() as cursor:
                        cursor.execute("RESET ROLE")
                finally:
                    connection.close()

        return PooledTenantConnection(SocketOwner(), raw, tid, uid)

    monkeypatch.setattr(db, "system_connection", system)
    monkeypatch.setattr(db, "app_role_connection", scoped)
    return scoped

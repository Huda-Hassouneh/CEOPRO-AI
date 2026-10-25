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

    monkeypatch.setattr(
        security, "is_token_revoked", lambda token, fail_closed=False: False
    )


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
def platform_owner_context(owner_db):
    """Use an existing disposable Platform Owner or create a scoped fixture.

    The schema intentionally permits one active platform owner. Individual
    billing tests must reuse an existing owner instead of inserting a second
    global owner, and must remove only the owner rows they created.
    """
    import uuid

    tenant_id = user_id = None
    created_workspace = created_member = created_company = created_user = False
    added_tenant_membership = False
    with owner_db.cursor() as cur:
        cur.execute("SELECT tenant_id FROM public.keel_platform_workspace WHERE singleton=TRUE")
        workspace = cur.fetchone()
        if workspace:
            tenant_id = str(workspace[0])
            cur.execute("SELECT user_id FROM public.keel_platform_members WHERE role_key='owner' AND status='active'")
            member = cur.fetchone()
            if member:
                user_id = str(member[0])
        if not user_id:
            user_id = str(uuid.uuid4())
            created_member = True
            if not tenant_id:
                tenant_id = str(uuid.uuid4())
                cur.execute(
                    "INSERT INTO public.companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,'Synthetic Platform Owner','US','USD')",
                    (tenant_id,),
                )
                created_company = True
            cur.execute(
                "INSERT INTO public.users(user_id,email,password_hash) VALUES(%s,%s,'test-only')",
                (user_id, f"billing-platform-owner-{user_id}@example.test"),
            )
            created_user = True
            cur.execute(
                "INSERT INTO public.keel_platform_members(user_id,role_key,status) VALUES(%s,'owner','active')",
                (user_id,),
            )
            if not workspace:
                cur.execute("INSERT INTO public.keel_platform_workspace(singleton,tenant_id) VALUES(TRUE,%s)", (tenant_id,))
                created_workspace = True
        cur.execute(
            "SELECT 1 FROM public.tenant_users WHERE tenant_id=%s AND user_id=%s AND removed_at IS NULL",
            (tenant_id, user_id),
        )
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO public.tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')",
                (tenant_id, user_id),
            )
            added_tenant_membership = True
    owner_db.commit()
    yield tenant_id, user_id
    if created_member or added_tenant_membership or created_workspace:
        with owner_db.cursor() as cur:
            if created_member:
                cur.execute("DELETE FROM public.keel_platform_members WHERE user_id=%s", (user_id,))
            if added_tenant_membership:
                cur.execute("DELETE FROM public.tenant_users WHERE tenant_id=%s AND user_id=%s", (tenant_id, user_id))
            if created_workspace:
                cur.execute("DELETE FROM public.keel_platform_workspace WHERE singleton=TRUE AND tenant_id=%s", (tenant_id,))
            if created_company:
                cur.execute("DELETE FROM public.companies WHERE tenant_id=%s", (tenant_id,))
            if created_user:
                cur.execute("DELETE FROM public.users WHERE user_id=%s", (user_id,))
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

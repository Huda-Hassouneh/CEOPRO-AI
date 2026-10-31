from pathlib import Path

import pytest
from pydantic import ValidationError

from src.ai.routers.platform import StandardPlanCreate


def test_standard_plan_create_contract_accepts_explicit_terms_without_activating_or_inventing_price():
    body = StandardPlanCreate.model_validate({
        "plan_key": "regional_plus",
        "display_name": "Regional Plus",
        "display_name_ar": "الإقليمي بلس",
        "description": "For regional teams.",
        "description_ar": "للأعمال الإقليمية.",
        "tier_level": 5,
        "currency": "USD",
        "monthly_price": "82.50",
        "trial_days": 7,
        "billing_periods": [{"period_code": "yearly", "discount_percent": "12.50"}],
        "reason": "Approved new catalog offer.",
    })
    assert body.monthly_price == 82.50
    assert body.billing_periods[0].period_code == "yearly"
    assert body.currency == "USD"


@pytest.mark.parametrize("key", ["Custom", "custom", "Bad Key", "-bad", "UPPER"])
def test_standard_plan_create_rejects_reserved_or_unstable_keys(key):
    with pytest.raises(ValidationError):
        StandardPlanCreate.model_validate({
            "plan_key": key, "display_name": "A Plan", "display_name_ar": "خطة",
            "tier_level": 1, "monthly_price": "10", "trial_days": 0, "reason": "Test",
        })


def test_database_plan_creation_is_owner_gated_audited_and_inactive_until_explicit_activation():
    migration = (Path(__file__).parents[2] / "infrastructure" / "database" / "migrations"
                 / "20261120000000_owner_standard_plan_creation.sql").read_text(encoding="utf-8")
    create = migration.split("CREATE OR REPLACE FUNCTION public.billing_owner_standard_plan_create", 1)[1].split("END $$;", 1)[0]
    assert "keel_active_principal(actor,tenant)" in create
    assert "m.role_key='owner'" in create
    assert "platform_disabled_at IS NOT NULL" in create
    assert "historical identities cannot be reused" in create
    assert "TRUE,FALSE,catalog_version" in create
    assert "standard_plan_create" in create
    assert "billing_plan_prices" in create
    assert "stripe_price_id" not in create  # Stripe remains a separate reconciliation action.


def test_new_standard_plan_activation_requires_a_monthly_price_and_canonical_allowance():
    migration = (Path(__file__).parents[2] / "infrastructure" / "database" / "migrations"
                 / "20261120000000_owner_standard_plan_creation.sql").read_text(encoding="utf-8")
    assert "period_code='monthly' AND retired_at IS NULL" in migration
    assert "usage_plan_limits WHERE plan_key=plan" in migration
    assert "usage_plan_entitlements WHERE plan_key=plan" in migration
    assert "needs a monthly price and at least one canonical allowance before activation" in migration


@pytest.mark.skipif(not __import__("os").getenv("AI_TEST_DATABASE_URL"), reason="requires disposable migrated test database")
def test_owner_creates_and_configures_a_new_plan_through_restricted_role_without_touching_existing_terms():
    import os
    import uuid
    from contextlib import closing
    from decimal import Decimal
    from urllib.parse import quote, urlparse, urlunparse

    import psycopg2
    from psycopg2.extras import Json
    psycopg2.extras.register_uuid()

    database_url = os.environ["AI_TEST_DATABASE_URL"]
    parsed = urlparse(database_url)
    app_url = urlunparse(parsed._replace(netloc=(
        f"ceopro_app:{quote(os.environ['APP_DB_PASSWORD'], safe='')}@{parsed.hostname}:{parsed.port or 5432}"
    )))
    tenant, actor = uuid.uuid4(), uuid.uuid4()
    plan_key = "owner_created_" + uuid.uuid4().hex[:10]
    email = f"{plan_key}@example.test"
    periods = [{"period_code": "yearly", "discount_percent": "12.50"}]
    payload = {
        "plan_key": plan_key, "display_name": "Owner Created Test",
        "display_name_ar": "\u062e\u0637\u0629 \u0627\u062e\u062a\u0628\u0627\u0631",
        "description": "Disposable creation test", "description_ar": "\u0627\u062e\u062a\u0628\u0627\u0631 \u0645\u0624\u0642\u062a",
        "currency": "USD", "monthly_price": "79.00", "tier_level": 9, "trial_days": 7,
        "billing_periods": periods, "reason": "Disposable integration verification",
    }

    with closing(psycopg2.connect(database_url)) as admin, admin:
        with admin.cursor() as cur:
            cur.execute("SELECT plan_key, monthly_price, is_active FROM public.usage_plans WHERE plan_key IN ('starter','growth','enterprise') ORDER BY plan_key")
            plans_before = cur.fetchall()
            cur.execute("SELECT plan_key, period_code, amount, stripe_price_id FROM public.billing_plan_prices WHERE plan_key IN ('starter','growth','enterprise') ORDER BY plan_key,period_code")
            prices_before = cur.fetchall()
            cur.execute("SELECT count(*) FROM public.billing_subscriptions")
            subscriptions_before = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM public.tenant_plan_assignments")
            assignments_before = cur.fetchone()[0]
            cur.execute("INSERT INTO public.companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,'Disposable Platform Workspace','JO','JOD')", (tenant,))
            cur.execute("INSERT INTO public.users(user_id,email,password_hash,full_name) VALUES(%s,%s,'not-a-real-login-hash','Disposable Owner')", (actor,email))
            cur.execute("INSERT INTO public.tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')", (tenant,actor))
            cur.execute("INSERT INTO public.keel_platform_workspace(singleton,tenant_id) VALUES(true,%s)", (tenant,))
            cur.execute("INSERT INTO public.keel_platform_members(user_id,role_key,status) VALUES(%s,'owner','active')", (actor,))

    with closing(psycopg2.connect(app_url)) as app, app:
        with app.cursor() as cur:
            cur.execute("SELECT current_user")
            assert cur.fetchone()[0] == "ceopro_app"
            cur.execute("SELECT set_config('app.current_tenant_id',%s,true),set_config('app.current_user_id',%s,true)", (str(tenant),str(actor)))
            cur.execute("SELECT public.billing_owner_standard_plan_create(%s::jsonb)", (Json(payload),))
            created = cur.fetchone()[0]
            assert created["is_active"] is False and created["stripe_setup_required"] is True
            assert created["plan"]["plan_key"] == plan_key
            assert Decimal(str(created["prices"][0]["amount"])) == Decimal("79.00")
            assert Decimal(str(created["prices"][1]["amount"])) == Decimal("829.50")
            cur.execute("SAVEPOINT incomplete_activation")
            with pytest.raises(psycopg2.errors.InvalidParameterValue):
                cur.execute("SELECT public.billing_owner_catalog_command(%s::jsonb)", (Json({
                    "action": "status", "plan_key": plan_key, "active": True, "reason": "Verify incomplete guard",
                }),))
            cur.execute("ROLLBACK TO SAVEPOINT incomplete_activation")
            for code, limit in (("ai_credits", 700), ("data_credits", 900), ("monthly_reports", 25)):
                command = {"action":"feature","plan_key":plan_key,"feature_code":code,
                           "included":True,"limit_value":limit,"reason":"Disposable feature assignment"}
                cur.execute("SELECT public.billing_owner_catalog_command(%s::jsonb)", (Json(command),))
            cur.execute("SELECT public.billing_platform_standard_plans_read(100,0)")
            read_model = cur.fetchone()[0]
            new_plan = next(row for row in read_model["plans"] if row["plan_key"] == plan_key)
            assert new_plan["feature_configured"] is True
            assert new_plan["configuration_status"] == "READY_TO_ACTIVATE"
            activation = {"action":"status","plan_key":plan_key,"active":True,"reason":"Disposable activation test"}
            cur.execute("SELECT public.billing_owner_catalog_command(%s::jsonb)", (Json(activation),))
            cur.execute("SELECT public.billing_platform_standard_plans_read(100,0)")
            active_model = cur.fetchone()[0]
            active_plan = next(row for row in active_model["plans"] if row["plan_key"] == plan_key)
            assert active_plan["is_active"] is True
            assert active_plan["configuration_status"] == "STRIPE_SETUP_REQUIRED"
            from src.ai.billing.service import _price_or_error, BillingError
            with pytest.raises(BillingError) as unsynced:
                _price_or_error(app, plan_key, "monthly")
            assert unsynced.value.code == "price_not_synced"
            app.commit()

    with closing(psycopg2.connect(database_url)) as admin, admin:
        with admin.cursor() as cur:
            cur.execute("SELECT plan_key, monthly_price, is_active FROM public.usage_plans WHERE plan_key IN ('starter','growth','enterprise') ORDER BY plan_key")
            assert cur.fetchall() == plans_before
            cur.execute("SELECT plan_key, period_code, amount, stripe_price_id FROM public.billing_plan_prices WHERE plan_key IN ('starter','growth','enterprise') ORDER BY plan_key,period_code")
            assert cur.fetchall() == prices_before
            cur.execute("SELECT count(*) FROM public.billing_subscriptions")
            assert cur.fetchone()[0] == subscriptions_before
            cur.execute("SELECT count(*) FROM public.tenant_plan_assignments")
            assert cur.fetchone()[0] == assignments_before
            cur.execute("SELECT count(*) FROM public.keel_platform_audit WHERE actor_user_id=%s AND subject=%s AND action='standard_plan_create' AND outcome='succeeded'", (actor,'plan:'+plan_key))
            assert cur.fetchone()[0] == 1
            # Keep the disposable plan out of subsequent tests' self-serve catalog.
            cur.execute("UPDATE public.usage_plans SET is_active=false,self_serve=false WHERE plan_key=%s", (plan_key,))
            cur.execute("UPDATE public.keel_platform_members SET role_key='admin' WHERE user_id=%s", (actor,))

    with closing(psycopg2.connect(app_url)) as app, app:
        with app.cursor() as cur:
            cur.execute("SELECT set_config('app.current_tenant_id',%s,true),set_config('app.current_user_id',%s,true)", (str(tenant),str(actor)))
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute("SELECT public.billing_owner_standard_plan_create(%s::jsonb)", (Json({**payload,"plan_key":plan_key+"_denied"}),))
            app.rollback()

    with closing(psycopg2.connect(database_url)) as admin, admin:
        with admin.cursor() as cur:
            cur.execute("UPDATE public.keel_platform_members SET role_key='owner' WHERE user_id=%s", (actor,))

    # Exercise the real HTTP boundary too; Stripe is never contacted by these routes.
    from fastapi.testclient import TestClient
    from src.ai.main import app as api
    from src.ai.core.security import create_access_token
    headers = {"Authorization": "Bearer " + create_access_token(str(tenant), str(actor), email_verified=True)[0]}
    with TestClient(api) as client:
        assert client.post("/platform/billing/plans", json=payload, headers=headers).status_code == 409
        assert client.post("/platform/billing/plans", json={**payload, "plan_key": "custom"}, headers=headers).status_code == 422
        http_key = plan_key + "_api"
        response = client.post("/platform/billing/plans", json={**payload, "plan_key": http_key,
            "display_name": "HTTP Owner Test", "display_name_ar": "\u062e\u0637\u0629 HTTP"}, headers=headers)
        assert response.status_code == 201, response.text
        assert response.json()["is_active"] is False
        status_url = f"/platform/billing/plans/{http_key}/status"
        command = {"active": True, "reason": "Verify HTTP activation guard"}
        assert client.patch(status_url, json=command, headers=headers).status_code == 422
        for code in ("ai_credits", "data_credits", "document_storage_mb", "market_intelligence"):
            response = client.patch(f"/platform/billing/plans/{http_key}/features", json={
                "feature_code": code, "included": True, "limit_value": None if code == "market_intelligence" else 700,
                "reason": "Verify HTTP feature configuration",
            }, headers=headers)
            assert response.status_code == 200, response.text
        assert client.patch(status_url, json=command, headers=headers).status_code == 200
        current = client.get("/platform/billing/standard-plans", headers=headers)
        assert current.status_code == 200
        row = next(p for p in current.json()["plans"] if p["plan_key"] == http_key)
        assert row["configuration_status"] == "STRIPE_SETUP_REQUIRED"
        assert client.patch(status_url, json={**command, "active": False}, headers=headers).status_code == 200

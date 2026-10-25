"""Native tests for versioned plan mutations and frozen tenant terms."""
import uuid

from src.ai.billing import admin as billing_admin
from src.ai.core import usage


def _new_tenant(conn):
    tenant_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO public.companies(tenant_id,business_name,country_code,primary_currency) "
            "VALUES(%s,'Synthetic catalog snapshot tenant','JO','JOD')", (tenant_id,)
        )
        cur.execute(
            "INSERT INTO public.users(user_id,email,password_hash) VALUES(%s,%s,'not-a-login-password')",
            (user_id, f"catalog-{user_id}@example.test"),
        )
        cur.execute("INSERT INTO public.tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')",
                    (tenant_id, user_id))
    return tenant_id, user_id


def test_owner_plan_quota_edit_is_audited_and_does_not_rewrite_existing_assignments(
    owner_db, tenant, test_price
):
    plan_key = test_price[0]
    with owner_db.cursor() as cur:
        cur.execute("INSERT INTO public.usage_plan_limits(plan_key,feature_code,limit_value) VALUES(%s,'team_seats',3)",
                    (plan_key,))
        cur.execute("INSERT INTO public.usage_plan_entitlements(plan_key,feature_code) VALUES(%s,'market_intelligence')",
                    (plan_key,))
        cur.execute(
            "INSERT INTO public.tenant_plan_assignments(tenant_id,plan_key,status,source) VALUES(%s,%s,'active','stripe')",
            (tenant[0], plan_key),
        )
        cur.execute("SELECT catalog_snapshot FROM public.tenant_plan_assignments WHERE tenant_id=%s", (tenant[0],))
        original_snapshot = cur.fetchone()[0]
    assert original_snapshot["features"]
    old_plan = usage.get_plan(owner_db, tenant[0])
    assert old_plan["features"]["team_seats"]["limit"] == 3
    assert "market_intelligence" in old_plan["entitlements"]

    result = billing_admin.set_plan_feature(
        owner_db, plan_key=plan_key, feature_code="team_seats", included=True, limit_value=9,
        approved_by=tenant[1], reason="SYNTHETIC_TEST_ONLY: catalog snapshot regression",
    )
    billing_admin.set_plan_feature(
        owner_db, plan_key=plan_key, feature_code="market_intelligence", included=False, limit_value=None,
        approved_by=tenant[1], reason="SYNTHETIC_TEST_ONLY: module entitlement regression",
    )
    owner_db.commit()
    assert result["catalog_versioned"] is True
    assert result["existing_assignments_preserved"] is True

    still_old = usage.get_plan(owner_db, tenant[0])
    assert still_old["features"]["team_seats"]["limit"] == 3
    assert "market_intelligence" in still_old["entitlements"]

    second_tenant, second_user = _new_tenant(owner_db)
    with owner_db.cursor() as cur:
        cur.execute(
            "INSERT INTO public.tenant_plan_assignments(tenant_id,plan_key,status,source) "
            "VALUES(%s,%s,'active','stripe')", (second_tenant, plan_key),
        )
        cur.execute("SELECT catalog_snapshot FROM public.tenant_plan_assignments WHERE tenant_id=%s", (second_tenant,))
        new_snapshot = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM public.keel_platform_audit WHERE actor_user_id=%s "
            "AND action='plan_feature_update' AND reason LIKE 'SYNTHETIC_TEST_ONLY:%%'", (tenant[1],),
        )
        audit_count = cur.fetchone()[0]
    assert any(item["feature_code"] == "team_seats" and item["limit_value"] == 9
               for item in new_snapshot["features"])
    assert "market_intelligence" not in new_snapshot["entitlements"]
    assert audit_count == 2
    new_plan = usage.get_plan(owner_db, second_tenant)
    assert new_plan["features"]["team_seats"]["limit"] == 9
    assert "market_intelligence" not in new_plan["entitlements"]

    with owner_db.cursor() as cur:
        cur.execute("DELETE FROM public.companies WHERE tenant_id=%s", (second_tenant,))
        cur.execute("DELETE FROM public.users WHERE user_id=%s", (second_user,))
    owner_db.commit()


def test_plan_feature_mutation_rejects_unsupported_or_invalid_values(owner_db, test_price):
    for feature_code, included, limit_value in (
        ("unknown_feature", True, 1), ("team_seats", True, -1), ("market_intelligence", True, 1),
    ):
        try:
            billing_admin.set_plan_feature(
                owner_db, plan_key=test_price[0], feature_code=feature_code, included=included,
                limit_value=limit_value, approved_by="synthetic-owner", reason="SYNTHETIC_TEST_ONLY: invalid input",
            )
        except billing_admin.AdminError:
            owner_db.rollback()
        else:
            raise AssertionError(f"invalid plan feature mutation was accepted: {feature_code}/{limit_value}")

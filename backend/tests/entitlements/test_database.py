"""Actual main schema and quota SQL, fixture-only writes to disposable database."""

import os
from datetime import UTC, date, datetime, timedelta

import pytest

from src.ai.billing import credits
from src.ai.core import usage
from src.ai.core.security import create_access_token


@pytest.mark.parametrize(
    "status",
    [
        "active",
        "trialing",
        "expired",
        "cancelled",
        "past_due",
        "payment_failed",
        "pending",
        "paused",
    ],
)
def test_status_effects_on_atomic_reservations(owner_db, assigned, status):
    tid, _ = assigned
    with owner_db.cursor() as cur:
        cur.execute(
            "UPDATE tenant_plan_assignments SET status=%s WHERE tenant_id=%s",
            (status, tid),
        )
    if status in usage.ACCESS_GRANTING_STATUSES:
        assert usage.reserve(owner_db, tid, usage.MONTHLY_REPORTS)["amount"] == 1
    else:
        with pytest.raises(usage.PlanLimitReached) as error:
            usage.reserve(owner_db, tid, usage.MONTHLY_REPORTS)
        assert error.value.reason == "SUBSCRIPTION_INACTIVE"


def test_missing_assignment_denies_consumption(owner_db, tenant):
    tid, _ = tenant
    assert usage.get_plan(owner_db, tid)["status"] == "none"
    with pytest.raises(usage.PlanLimitReached):
        usage.reserve(owner_db, tid, usage.MONTHLY_REPORTS)


def test_catalog_mapping_is_resolved_from_actual_main_tables(owner_db, assigned):
    tid, _ = assigned
    result = usage.get_plan(owner_db, tid)
    with owner_db.cursor() as cur:
        cur.execute(
            "SELECT feature_code FROM usage_plan_entitlements WHERE plan_key='standard' ORDER BY feature_code"
        )
        assert result["entitlements"] == [row[0] for row in cur.fetchall()]
        cur.execute(
            "SELECT limit_value FROM usage_plan_limits WHERE plan_key='standard' AND feature_code=%s",
            (usage.MONTHLY_REPORTS,),
        )
        assert result["features"][usage.MONTHLY_REPORTS]["limit"] == cur.fetchone()[0]


def test_credit_budgets_include_reserved_units_and_remain_separate(
    owner_db, assigned, billing_connections
):
    tid, _ = assigned
    plan = usage.get_plan(owner_db, tid)
    limit = plan["features"][usage.DATA_CREDITS]["limit"]
    assert limit > 0
    with owner_db.cursor() as cur:
        cur.execute(
            "INSERT INTO tenant_credit_balances(tenant_id,budget_kind,period_start,period_end,consumed_credits,reserved_credits) VALUES(%s,'data',%s,%s,%s,1)",
            (tid, plan["period_start"], plan["period_end"], limit - 1),
        )
    with pytest.raises(credits.BudgetError) as error:
        credits.ensure_available(tid, credits.DATA)
    assert error.value.reason == "BUDGET_EXHAUSTED"
    credits.ensure_available(tid, credits.AI)
    item = next(
        x
        for x in usage.current_usage(owner_db, tid)
        if x["feature_code"] == usage.DATA_CREDITS
    )
    assert item["current_usage"] == limit and item["remaining"] == 0


def test_missing_report_limit_fails_closed_but_explicit_null_is_unlimited(
    owner_db, assigned
):
    tid, _ = assigned
    plan = usage.get_plan(owner_db, tid)
    # Synthetic resolver edge cases, real reservation SQL; do not rewrite catalog
    # terms. Main's actual Custom report/credit budgets are finite.
    from unittest.mock import patch

    plan["features"][usage.MONTHLY_REPORTS]["limit"] = None
    with patch.object(usage, "get_plan", return_value=plan):
        assert (
            usage.reserve(owner_db, tid, usage.MONTHLY_REPORTS, 100000)["amount"]
            == 100000
        )
    plan["features"].pop(usage.MONTHLY_REPORTS)
    with (
        patch.object(usage, "get_plan", return_value=plan),
        pytest.raises(usage.PlanLimitReached),
    ):
        usage.reserve(owner_db, tid, usage.MONTHLY_REPORTS)


def test_missing_plan_limit_fails_closed_for_sum_and_live_capacity(owner_db, assigned):
    from uuid import uuid4

    tid, _ = assigned
    unconfigured_plan = f"missing_limit_{uuid4().hex[:12]}"
    with owner_db.cursor() as cur:
        cur.execute(
            "INSERT INTO usage_plans(plan_key,display_name) VALUES(%s,'Missing limit test')",
            (unconfigured_plan,),
        )
        cur.execute(
            "UPDATE tenant_plan_assignments SET plan_key=%s WHERE tenant_id=%s",
            (unconfigured_plan, tid),
        )

    try:
        assert usage.remaining(owner_db, tid, usage.RAG_ASSISTANT) == 0
        with pytest.raises(usage.PlanLimitReached) as metered:
            usage.reserve(owner_db, tid, usage.RAG_ASSISTANT)
        assert metered.value.reason == "QUOTA_EXHAUSTED"

        assert usage.capacity_left(owner_db, tid, usage.TRACKED_PRODUCTS) == 0
        with pytest.raises(usage.PlanLimitReached) as capacity:
            usage.ensure_capacity(owner_db, tid, usage.TRACKED_PRODUCTS)
        assert capacity.value.reason == "CAPACITY_REACHED"
    finally:
        with owner_db.cursor() as cur:
            cur.execute(
                "UPDATE tenant_plan_assignments SET plan_key='standard' WHERE tenant_id=%s",
                (tid,),
            )
            cur.execute("DELETE FROM usage_plans WHERE plan_key=%s", (unconfigured_plan,))


def test_atomic_limit_release_and_read_contract(owner_db, assigned):
    tid, _ = assigned
    plan = usage.get_plan(owner_db, tid)
    limit = plan["features"][usage.MONTHLY_REPORTS]["limit"]
    reservation = usage.reserve(owner_db, tid, usage.MONTHLY_REPORTS, limit)
    with pytest.raises(usage.PlanLimitReached) as error:
        usage.reserve(owner_db, tid, usage.MONTHLY_REPORTS)
    assert error.value.reason == "QUOTA_EXHAUSTED"
    usage.release(owner_db, reservation)
    item = next(
        x
        for x in usage.current_usage(owner_db, tid)
        if x["feature_code"] == usage.MONTHLY_REPORTS
    )
    assert (item["current_usage"], item["remaining"], item["reset_cycle"]) == (
        0,
        limit,
        "billing_period",
    )


def test_live_product_capacity(owner_db, assigned):
    tid, _ = assigned
    with owner_db.cursor() as cur:
        cur.execute(
            "INSERT INTO tenant_entitlement_overrides(tenant_id,feature_code,limit_value,contract_ref,approved_by,reason) VALUES(%s,%s,0,'test-fixture','test-runner','capacity regression')",
            (tid, usage.TRACKED_PRODUCTS),
        )
    with pytest.raises(usage.PlanLimitReached) as error:
        usage.ensure_capacity(owner_db, tid, usage.TRACKED_PRODUCTS)
    assert error.value.reason == "CAPACITY_REACHED"


def test_sum_counter_reset_selects_new_period_retains_old_history(owner_db, assigned):
    tid, _ = assigned
    previous = date.today().replace(day=1) - timedelta(days=1)
    previous = previous.replace(day=1)
    with owner_db.cursor() as cur:
        cur.execute(
            "INSERT INTO tenant_usage_counters(tenant_id,feature_code,period_start,used) VALUES(%s,%s,%s,999)",
            (tid, usage.MONTHLY_REPORTS, previous),
        )
    result = usage.reserve(owner_db, tid, usage.MONTHLY_REPORTS)
    assert result["period_start"] == date.today().replace(day=1)
    with owner_db.cursor() as cur:
        cur.execute(
            "SELECT used FROM tenant_usage_counters WHERE tenant_id=%s AND period_start=%s",
            (tid, previous),
        )
        assert cur.fetchone()[0] == 999


def test_exact_free_trial_expiry(owner_db, assigned):
    tid, _ = assigned
    now = datetime.now(UTC)
    with owner_db.cursor() as cur:
        cur.execute(
            "UPDATE tenant_plan_assignments SET status='trialing',source='trial' WHERE tenant_id=%s",
            (tid,),
        )
        cur.execute(
            "INSERT INTO billing_trials(tenant_id,plan_key,started_at,ends_at) VALUES(%s,'standard',%s,%s)",
            (tid, now - timedelta(days=7), now - timedelta(seconds=1)),
        )
    assert usage.get_plan(owner_db, tid, now=now)["status"] == "expired"


def test_same_report_retry_counts_once(owner_db, assigned, billing_connections):
    tid, uid = assigned
    one = usage.reserve_request(tid, usage.MONTHLY_REPORTS, "same-report-key", uid)
    two = usage.reserve_request(tid, usage.MONTHLY_REPORTS, "same-report-key", uid)
    assert one and two is None


def test_old_report_key_cannot_bypass_inactive_subscription(
    owner_db, assigned, billing_connections
):
    tid, uid = assigned
    usage.reserve_request(tid, usage.MONTHLY_REPORTS, "same-report-key", uid)
    with owner_db.cursor() as cur:
        cur.execute(
            "UPDATE tenant_plan_assignments SET status='cancelled' WHERE tenant_id=%s",
            (tid,),
        )
    with pytest.raises(usage.PlanLimitReached, match="SUBSCRIPTION_INACTIVE"):
        usage.reserve_request(tid, usage.MONTHLY_REPORTS, "same-report-key", uid)


def test_old_period_report_key_counts_in_current_period(
    owner_db, assigned, billing_connections
):
    tid, uid = assigned
    previous = date.today().replace(day=1) - timedelta(days=1)
    with owner_db.cursor() as cur:
        cur.execute(
            "INSERT INTO metered_request_keys(tenant_id,feature_code,idempotency_key,period_start,actor_user_id) VALUES(%s,%s,'old-period-key',%s,%s)",
            (tid, usage.MONTHLY_REPORTS, previous.replace(day=1), uid),
        )
    assert (
        usage.reserve_request(tid, usage.MONTHLY_REPORTS, "old-period-key", uid)
        is not None
    ), "A previous billing period's key must not suppress current accounting"


@pytest.mark.parametrize("amount", [0, -1, 1.5])
def test_reservations_require_positive_integer_amount(owner_db, assigned, amount):
    tid, _ = assigned
    usage.reserve(owner_db, tid, usage.MONTHLY_REPORTS, 2)
    with pytest.raises((ValueError, TypeError)):
        usage.reserve(owner_db, tid, usage.MONTHLY_REPORTS, amount)


def test_runtime_role_can_meter_rag_without_elevating_privileges(
    assigned, billing_connections
):
    tid, uid = assigned
    conn = billing_connections(tid, uid)
    try:
        assert usage.reserve(conn, tid, usage.RAG_ASSISTANT)["amount"] == 1
        conn.commit()
    finally:
        conn.close()


def test_tenant_cannot_read_another_tenants_assignment_or_counter(
    owner_db, assigned, billing_connections, other_tenant
):
    tid, uid = assigned
    usage.reserve(owner_db, tid, usage.MONTHLY_REPORTS)
    conn = billing_connections(tid, uid)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tenant_id FROM tenant_plan_assignments WHERE tenant_id <> %s",
                (tid,),
            )
            assert cur.fetchall() == []
            cur.execute(
                "SELECT tenant_id FROM tenant_usage_counters WHERE tenant_id <> %s",
                (tid,),
            )
            assert cur.fetchall() == []
        conn.commit()
    finally:
        conn.close()


def test_forged_tenant_context_cannot_resolve_other_plan(
    assigned, other_tenant, billing_connections
):
    _, uid = assigned
    conn = billing_connections(other_tenant, uid)
    try:
        plan = usage.get_plan(conn, other_tenant)
        assert plan["assigned"] is False and plan["status"] == "none"
    finally:
        conn.close()


def test_subscription_contract_remains_reachable_when_inactive(
    client, owner_db, assigned, billing_connections
):
    tid, uid = assigned
    with owner_db.cursor() as cur:
        cur.execute(
            "UPDATE tenant_plan_assignments SET status='cancelled' WHERE tenant_id=%s",
            (tid,),
        )
    result = client.get(
        "/billing/subscription",
        headers={
            "Authorization": "Bearer "
            + create_access_token(tid, uid, email_verified=True)[0]
        },
    )
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["hasAccess"] is False
    assert {
        "features",
        "entitlements",
        "limits",
        "usage",
        "credits",
        "periodStart",
        "periodEnd",
    } <= data.keys()


def test_real_multi_session_atomicity(owner_db, assigned):
    if os.getenv("BILLING_TEST_ENGINE") == "pglite":
        pytest.skip(
            "PGlite multiplexes a single backend; native PostgreSQL concurrency required"
        )
    import threading

    import psycopg2

    from scripts.billing_verification import validate_test_environment

    tid, _ = assigned
    limit = usage.get_plan(owner_db, tid)["features"][usage.MONTHLY_REPORTS]["limit"]
    usage.reserve(owner_db, tid, usage.MONTHLY_REPORTS, limit - 1)
    url = validate_test_environment(dict(os.environ), database=True)
    granted, errors = [], []

    def worker():
        conn = psycopg2.connect(
            url, connect_timeout=5, options="-c statement_timeout=5000"
        )
        try:
            usage.reserve(conn, tid, usage.MONTHLY_REPORTS)
            conn.commit()
            granted.append(1)
        except usage.PlanLimitReached:
            conn.rollback()
        except psycopg2.Error as exc:
            errors.append(type(exc).__name__)
        finally:
            conn.close()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not any(thread.is_alive() for thread in threads)
    assert not errors and len(granted) == 1

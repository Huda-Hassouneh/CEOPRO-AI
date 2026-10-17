"""
Data Credits and AI Credits against a real Postgres (billing/credits.py):
budgets per plan, exhaustion, concurrent reservations, idempotency, paid and
unpaid provider failures, reconciliation, provider caps and kill switches,
tenant isolation, and the AI and data call paths that spend them.

Every test prices its own made-up provider, so nothing here depends on (or
changes) a real provider's price or the global kill switch.
"""
import os
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import psycopg2
import pytest

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")

from src.ai.billing import admin, cost_model, credits  # noqa: E402
from src.ai.core import usage  # noqa: E402


@pytest.fixture(autouse=True)
def _metering_on(monkeypatch):
    monkeypatch.delenv("KEEL_TEST_DISABLE_METERING", raising=False)
    monkeypatch.setenv("UNASSIGNED_PLAN_ACCESS", "none")


@pytest.fixture
def sys_conn():
    conn = psycopg2.connect(DATABASE_URL)
    yield conn
    conn.rollback()
    conn.close()


def _company(conn, plan_key="starter", status="active", source="manual") -> str:
    tenant_id = str(uuid.uuid4())
    today = datetime.now(timezone.utc).date()
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, %s, 'JO', 'JOD');",
            (tenant_id, f"Credits Test {tenant_id[:8]}"),
        )
        if plan_key:
            cursor.execute(
                "INSERT INTO tenant_plan_assignments (tenant_id, plan_key, status, current_period_start, current_period_end, source) "
                "VALUES (%s, %s, %s, %s, %s, %s);",
                (tenant_id, plan_key, status, today.replace(day=1), today.replace(day=1) + timedelta(days=40), source),
            )
    conn.commit()
    return tenant_id


def _provider(conn, kind="data", unit="request", usd="0.05", charged_on_failure=True, final=True) -> str:
    name = f"test_{uuid.uuid4().hex[:10]}"
    admin.set_price(conn, budget_kind=kind, provider=name, operation="op", unit=unit, unit_cost_usd=Decimal(usd),
                    source="test", verified_on=date.today(), approved_by="test", reason="test", safety_margin=Decimal("0"),
                    charged_on_failure=charged_on_failure, cost_is_final=final)
    conn.commit()
    return name


def _ai_provider(conn, input_usd="0.000002", output_usd="0.000008") -> str:
    name = f"test_ai_{uuid.uuid4().hex[:8]}"
    for unit, usd in (("input_token", input_usd), ("output_token", output_usd)):
        admin.set_price(conn, budget_kind="ai", provider=name, operation="*", unit=unit, unit_cost_usd=Decimal(usd),
                        source="test", verified_on=date.today(), approved_by="test", reason="test", safety_margin=Decimal("0"))
    conn.commit()
    return name


def _balance(conn, tenant, kind="data"):
    conn.rollback()
    with conn.cursor() as cursor:
        cursor.execute("SELECT reserved_credits, consumed_credits FROM tenant_credit_balances WHERE tenant_id = %s AND budget_kind = %s;",
                       (tenant, kind))
        row = cursor.fetchone()
    conn.rollback()
    return (Decimal(row[0]), Decimal(row[1])) if row else (Decimal(0), Decimal(0))


def _ledger(conn, tenant):
    conn.rollback()
    with conn.cursor() as cursor:
        cursor.execute("SELECT status, consumed_credits, actual_cost_usd, provider, provider_operation, estimated_units, "
                       "measured_units, idempotency_key FROM usage_ledger WHERE tenant_id = %s ORDER BY created_at;", (tenant,))
        rows = cursor.fetchall()
    conn.rollback()
    return rows


# --- plans and budgets -------------------------------------------------------------

def test_plan_budgets_match_the_cost_model(sys_conn):
    """The credit numbers in the migration are exactly the documented cost model's output."""
    expected = cost_model.recommended_budgets()
    with sys_conn.cursor() as cursor:
        cursor.execute("SELECT plan_key, feature_code, limit_value, trial_limit_value FROM usage_plan_limits "
                       "WHERE feature_code IN ('data_credits', 'ai_credits') AND plan_key IN ('starter', 'growth', 'enterprise');")
        rows = {(p, f): (v, t) for p, f, v, t in cursor.fetchall()}
    for plan_key, budget in expected.items():
        assert rows[(plan_key, "data_credits")] == (budget.data_credits, budget.trial_data_credits)
        assert rows[(plan_key, "ai_credits")] == (budget.ai_credits, budget.trial_ai_credits)


def test_variable_cost_formula_follows_the_spec():
    # $100 net revenue at a 70% contribution margin leaves $30 for variable cost.
    assert cost_model.max_variable_cost(Decimal("100"), Decimal("0.70")) == Decimal("30.00")
    with pytest.raises(ValueError):
        cost_model.max_variable_cost(Decimal("100"), Decimal("1"))


@pytest.mark.parametrize("plan_key, products, reports, seats, trial_days", [
    ("starter", 100, 5, 5, 14), ("growth", 250, 20, 20, 14), ("enterprise", 500, 60, 50, 7)])
def test_every_plan_has_its_entitlements(sys_conn, plan_key, products, reports, seats, trial_days):
    tenant = _company(sys_conn, plan_key)
    plan = usage.get_plan(sys_conn, tenant)
    limits = {code: f["limit"] for code, f in plan["features"].items()}
    assert (limits["tracked_products"], limits["monthly_reports"], limits["team_seats"]) == (products, reports, seats)
    assert limits["tracked_competitors"] is None  # budget-based, no fixed count
    with sys_conn.cursor() as cursor:
        cursor.execute("SELECT trial_days FROM usage_plans WHERE plan_key = %s;", (plan_key,))
        assert cursor.fetchone()[0] == trial_days


def test_a_trial_gets_the_bounded_trial_budget(sys_conn):
    tenant = _company(sys_conn, "growth", status="trialing", source="trial")
    plan = usage.get_plan(sys_conn, tenant)
    assert plan["features"]["data_credits"]["limit"] == 111 and plan["features"]["ai_credits"]["limit"] == 111


# --- reservations ------------------------------------------------------------------

def test_spending_stops_exactly_at_the_budget(sys_conn):
    tenant = _company(sys_conn, "starter")          # 436 Data Credits
    provider = _provider(sys_conn, usd="1.00")      # 100 credits per request
    with credits.metering(tenant, "test"):
        for _ in range(4):
            with credits.provider_call("data", provider, "op", {"request": 1}) as call:
                call.measured({"request": 1})
        with pytest.raises(credits.BudgetError) as refused:
            credits.reserve("data", provider, "op", {"request": 1})
    assert refused.value.reason == "BUDGET_EXHAUSTED" and refused.value.status_code == 402
    assert _balance(sys_conn, tenant) == (Decimal("0"), Decimal("400"))
    with pytest.raises(credits.BudgetError):
        # 36 left: smaller work still fits, but nothing past the limit.
        with credits.metering(tenant, "test"):
            credits.reserve("data", provider, "op", {"request": 0.5})
    with credits.metering(tenant, "test"):
        credits.reserve("data", provider, "op", {"request": 0.3})  # 30 credits: fits


def test_exhausted_budget_refuses_new_discretionary_work(sys_conn):
    tenant = _company(sys_conn, "starter")
    admin.adjust_credits(sys_conn, tenant_id=tenant, budget_kind="data", credits_delta=Decimal("436"),
                         reference=f"t-{uuid.uuid4().hex[:6]}", approved_by="test", reason="test")
    sys_conn.commit()
    with pytest.raises(credits.BudgetError) as refused:
        credits.ensure_available(tenant, "data")
    assert refused.value.reason == "BUDGET_EXHAUSTED"
    credits.ensure_available(tenant, "ai")  # the other budget is separate


def test_recovery_operations_may_finish_past_the_budget_but_customer_work_may_not(sys_conn):
    tenant = _company(sys_conn, "starter")
    provider = _provider(sys_conn, usd="10.00")     # 1,000 credits: more than the whole budget
    with pytest.raises(ValueError):
        with credits.metering(tenant, "assistant_question", allow_over_budget=True):
            pass
    with credits.metering(tenant, "reconciliation", allow_over_budget=True):
        credits.reserve("data", provider, "op", {"request": 1})
    with credits.metering(tenant, "market_discovery"):
        with pytest.raises(credits.BudgetError):
            credits.reserve("data", provider, "op", {"request": 1})


def test_concurrent_requests_cannot_overspend(sys_conn):
    tenant = _company(sys_conn, "starter")          # 436 credits
    provider = _provider(sys_conn, usd="0.50")      # 50 credits each: at most 8 fit
    outcomes = []

    def spend():
        with credits.metering(tenant, "test"):
            try:
                credits.reserve("data", provider, "op", {"request": 1})
                outcomes.append("ok")
            except credits.BudgetError as err:
                outcomes.append(err.reason)

    threads = [threading.Thread(target=spend) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes.count("ok") == 8 and outcomes.count("BUDGET_EXHAUSTED") == 12
    reserved, consumed = _balance(sys_conn, tenant)
    assert reserved + consumed == Decimal("400") <= Decimal("436")


def test_a_replayed_operation_is_neither_charged_nor_run_twice(sys_conn):
    tenant = _company(sys_conn, "starter")
    provider = _provider(sys_conn)
    with credits.metering(tenant, "test", idempotency_key="client-key-123"):
        with credits.provider_call("data", provider, "op", {"request": 1}) as call:
            call.measured({"request": 1})
    ran = []
    with credits.metering(tenant, "test", idempotency_key="client-key-123"):
        with pytest.raises(credits.BudgetError) as duplicate:
            with credits.provider_call("data", provider, "op", {"request": 1}):
                ran.append(True)
    assert duplicate.value.reason == "DUPLICATE_REQUEST" and duplicate.value.status_code == 409 and not ran
    assert len(_ledger(sys_conn, tenant)) == 1


def test_settling_twice_never_double_counts(sys_conn):
    tenant = _company(sys_conn, "starter")
    provider = _provider(sys_conn, usd="0.10")
    with credits.metering(tenant, "test"):
        reservation = credits.reserve("data", provider, "op", {"request": 1})
    credits.settle(reservation, {"request": 1})
    reservation.settled = False                      # e.g. a retried settlement message
    assert credits.settle(reservation, {"request": 1}) == 0
    assert _balance(sys_conn, tenant) == (Decimal("0"), Decimal("10"))


# --- provider failures -------------------------------------------------------------

def test_a_failure_the_provider_bills_is_charged(sys_conn):
    tenant = _company(sys_conn, "starter")
    provider = _provider(sys_conn, usd="0.20", charged_on_failure=True)
    with credits.metering(tenant, "test"):
        with pytest.raises(RuntimeError):
            with credits.provider_call("data", provider, "op", {"request": 1}) as call:
                call.sent()
                raise RuntimeError("provider timed out after receiving the request")
    [(status, consumed, *_)] = _ledger(sys_conn, tenant)
    assert status == "pending_reconciliation" and consumed == Decimal("20")


def test_a_failure_before_sending_or_not_billed_is_released(sys_conn):
    tenant = _company(sys_conn, "starter")
    billed_on_failure = _provider(sys_conn, usd="0.20", charged_on_failure=True)
    free_on_failure = _provider(sys_conn, usd="0.20", charged_on_failure=False)
    with credits.metering(tenant, "test"):
        with pytest.raises(RuntimeError):
            with credits.provider_call("data", billed_on_failure, "op", {"request": 1}):
                raise RuntimeError("never sent")
        with pytest.raises(RuntimeError):
            with credits.provider_call("data", free_on_failure, "op", {"request": 1}) as call:
                call.sent()
                raise RuntimeError("sent, but this provider doesn't bill failures")
        with credits.provider_call("data", billed_on_failure, "op", {"request": 1}):
            pass                                     # an error response the provider doesn't bill
    assert [row[0] for row in _ledger(sys_conn, tenant)] == ["released", "released", "released"]
    assert _balance(sys_conn, tenant) == (Decimal("0"), Decimal("0"))


def test_a_paid_retry_is_charged_as_its_own_call(sys_conn):
    tenant = _company(sys_conn, "starter")
    provider = _provider(sys_conn, usd="0.10")
    with credits.metering(tenant, "test"):
        for _attempt in range(2):
            with credits.provider_call("data", provider, "op", {"request": 1}) as call:
                call.measured({"request": 1})
    assert _balance(sys_conn, tenant) == (Decimal("0"), Decimal("20"))


# --- reconciliation ----------------------------------------------------------------

def test_delayed_provider_cost_is_reconciled_once(sys_conn):
    tenant = _company(sys_conn, "starter")
    provider = _provider(sys_conn, usd="0.10", final=False)  # billed later (like Apify)
    with credits.metering(tenant, "test"):
        with credits.provider_call("data", provider, "op", {"request": 1}) as call:
            call.measured({"request": 1})
    [(status, consumed, *_)] = _ledger(sys_conn, tenant)
    assert status == "pending_reconciliation" and consumed == Decimal("11.5")  # 10 + the 15% default margin
    with sys_conn.cursor() as cursor:
        cursor.execute("SELECT ledger_id FROM usage_ledger WHERE tenant_id = %s;", (tenant,))
        ledger_id = cursor.fetchone()[0]
    assert credits.reconcile(sys_conn, ledger_id, Decimal("0.08"), reference="inv-1", actor="test") == Decimal("-3.5")
    sys_conn.commit()
    assert credits.reconcile(sys_conn, ledger_id, Decimal("0.08"), reference="inv-1", actor="test") == 0
    sys_conn.commit()
    assert _balance(sys_conn, tenant) == (Decimal("0"), Decimal("8"))
    assert _ledger(sys_conn, tenant)[0][0] == "reconciled"


def test_a_crashed_call_keeps_counting_and_is_charged_later(sys_conn):
    tenant = _company(sys_conn, "starter")
    provider = _provider(sys_conn, usd="0.30")
    with credits.metering(tenant, "test"):
        credits.reserve("data", provider, "op", {"request": 1})  # the process "dies" here
    assert _balance(sys_conn, tenant) == (Decimal("30"), Decimal("0"))
    with sys_conn.cursor() as cursor:
        cursor.execute("UPDATE usage_ledger SET created_at = NOW() - INTERVAL '2 hours' WHERE tenant_id = %s;", (tenant,))
        # the guard allows this: the row is still 'reserved' and no money column changes
    sys_conn.commit()
    assert credits.expire_stale_reservations(sys_conn) >= 1
    sys_conn.commit()
    assert _balance(sys_conn, tenant) == (Decimal("0"), Decimal("30"))


def test_settled_ledger_rows_and_adjustments_are_immutable(sys_conn):
    tenant = _company(sys_conn, "starter")
    provider = _provider(sys_conn)
    with credits.metering(tenant, "test"):
        with credits.provider_call("data", provider, "op", {"request": 1}) as call:
            call.measured({"request": 1})
    with sys_conn.cursor() as cursor:
        with pytest.raises(psycopg2.Error):
            cursor.execute("UPDATE usage_ledger SET consumed_credits = 0 WHERE tenant_id = %s;", (tenant,))
        sys_conn.rollback()
        with pytest.raises(psycopg2.Error):
            cursor.execute("DELETE FROM usage_ledger WHERE tenant_id = %s;", (tenant,))
        sys_conn.rollback()
    admin.adjust_credits(sys_conn, tenant_id=tenant, budget_kind="data", credits_delta=Decimal("-5"), reference="r1",
                         approved_by="test", reason="goodwill")
    sys_conn.commit()
    with sys_conn.cursor() as cursor:
        with pytest.raises(psycopg2.Error):
            cursor.execute("UPDATE usage_ledger_adjustments SET credits_delta = -500 WHERE tenant_id = %s;", (tenant,))
    sys_conn.rollback()
    with sys_conn.cursor() as cursor:  # deleting the company removes its records (privacy), and only then
        cursor.execute("DELETE FROM companies WHERE tenant_id = %s;", (tenant,))
    sys_conn.commit()


# --- spending controls -------------------------------------------------------------

def test_kill_switch_and_platform_cap(sys_conn):
    tenant = _company(sys_conn, "enterprise")
    provider = _provider(sys_conn, usd="0.10")
    admin.set_control(sys_conn, provider=provider, approved_by="test", reason="incident", kill_switch=True)
    sys_conn.commit()
    with credits.metering(tenant, "test"):
        with pytest.raises(credits.BudgetError) as off:
            credits.reserve("data", provider, "op", {"request": 1})
    assert off.value.reason == "PROVIDER_DISABLED"
    admin.set_control(sys_conn, provider=provider, approved_by="test", reason="resolved", kill_switch=False,
                      monthly_cap_usd=Decimal("0.25"))
    sys_conn.commit()
    with credits.metering(tenant, "test"):
        for _ in range(2):
            with credits.provider_call("data", provider, "op", {"request": 1}) as call:
                call.measured({"request": 1})
        with pytest.raises(credits.BudgetError) as capped:
            credits.reserve("data", provider, "op", {"request": 1})
    assert capped.value.reason == "PROVIDER_CAP_REACHED"


def test_an_unpriced_provider_is_refused_and_never_called(sys_conn):
    tenant = _company(sys_conn, "enterprise")
    called = []
    with credits.metering(tenant, "test"):
        with pytest.raises(credits.BudgetError) as refused:
            with credits.provider_call("data", f"unpriced_{uuid.uuid4().hex[:6]}", "op", {"request": 1}):
                called.append(True)
    assert refused.value.reason == "COST_NOT_CONFIGURED" and not called


def test_a_paid_call_outside_any_company_is_refused(sys_conn):
    provider = _provider(sys_conn)
    with pytest.raises(credits.BudgetError) as refused:
        credits.reserve("data", provider, "op", {"request": 1})
    assert refused.value.reason == "NO_BILLING_CONTEXT"


def test_inactive_and_unassigned_companies_cannot_spend(sys_conn):
    provider = _provider(sys_conn)
    for tenant in (_company(sys_conn, "starter", status="cancelled"), _company(sys_conn, None)):
        with credits.metering(tenant, "test"):
            with pytest.raises(credits.BudgetError) as refused:
                credits.reserve("data", provider, "op", {"request": 1})
        assert refused.value.reason == "SUBSCRIPTION_INACTIVE"


def test_accounting_outage_fails_closed(sys_conn):
    tenant = _company(sys_conn, "starter")
    provider = _provider(sys_conn)

    def broken():
        raise psycopg2.OperationalError("database unreachable")

    with credits.metering(tenant, "test"):
        with pytest.raises(credits.BudgetError) as refused:
            credits.reserve("data", provider, "op", {"request": 1}, conn_factory=broken)
    assert refused.value.reason == "ACCOUNTING_UNAVAILABLE"


def test_customer_errors_never_reveal_providers_or_prices(sys_conn):
    tenant = _company(sys_conn, "starter")
    provider = _provider(sys_conn, usd="99")
    with credits.metering(tenant, "test"):
        with pytest.raises(credits.BudgetError) as refused:
            credits.reserve("data", provider, "op", {"request": 1})
    body = str(refused.value.as_http().detail)
    assert provider not in body and "99" not in body and "usd" not in body.lower()


# --- tenant isolation --------------------------------------------------------------

def test_companies_see_only_their_own_usage_and_cannot_write_it(sys_conn):
    from src.ai import db

    a, b = _company(sys_conn, "starter"), _company(sys_conn, "starter")
    provider = _provider(sys_conn)
    with credits.metering(a, "test"):
        with credits.provider_call("data", provider, "op", {"request": 1}) as call:
            call.measured({"request": 1})
    user = str(uuid.uuid4())
    with sys_conn.cursor() as cursor:
        cursor.execute("INSERT INTO users (user_id, email, password_hash, full_name) VALUES (%s, %s, 'x', 'B');",
                       (user, f"b-{user[:8]}@example.com"))
        cursor.execute("INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, 'owner');", (b, user))
    sys_conn.commit()
    conn_b = db.dedicated_tenant_connection(b, user)
    try:
        with conn_b.cursor() as cursor:
            for table in ("usage_ledger", "tenant_credit_balances", "usage_ledger_adjustments"):
                cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE tenant_id = %s;", (a,))
                assert cursor.fetchone()[0] == 0, table
        assert credits.summary(conn_b, b)["data"]["consumed"] == 0
        for statement, params in (
            ("UPDATE tenant_credit_balances SET consumed_credits = 0;", ()),
            ("INSERT INTO tenant_credit_balances (tenant_id, budget_kind, period_start, period_end) VALUES (%s, 'data', CURRENT_DATE, CURRENT_DATE);", (b,)),
            ("INSERT INTO tenant_entitlement_overrides (tenant_id, feature_code, limit_value, contract_ref, approved_by, reason) "
             "VALUES (%s, 'ai_credits', 999999, 'x', 'me', 'me');", (b,)),
            ("UPDATE provider_cost_schedules SET unit_cost_usd = 0;", ()),
            ("UPDATE provider_spend_controls SET kill_switch = FALSE;", ()),
            ("UPDATE usage_plan_limits SET limit_value = NULL;", ()),
            ("UPDATE tenant_plan_assignments SET plan_key = 'enterprise';", ()),
        ):
            with pytest.raises(psycopg2.Error):
                cursor = conn_b.cursor()
                cursor.execute(statement, params)
            conn_b.rollback()
    finally:
        conn_b.rollback()
        conn_b.close()


# --- AI path -----------------------------------------------------------------------

class _Response:
    def __init__(self, status, body):
        self.status_code, self._body, self.text, self.headers = status, body, str(body), {}

    def json(self):
        return self._body


def _answer(content="ok", prompt=1000, completion=500):
    return _Response(200, {"id": "chatcmpl-1", "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                           "usage": {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}})


@pytest.fixture
def ai(sys_conn, monkeypatch):
    from src.ai.rag import llm_client

    provider = _ai_provider(sys_conn)
    monkeypatch.setattr(llm_client, "active_provider", lambda: provider)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_secret_never_logged")
    return llm_client, provider


def test_ai_calls_are_charged_by_measured_tokens(sys_conn, ai, monkeypatch):
    llm_client, provider = ai
    tenant = _company(sys_conn, "starter")
    monkeypatch.setattr(llm_client, "_post_with_retry", lambda *a, **k: _answer(prompt=1000, completion=500))
    with credits.metering(tenant, "assistant_question", usage_class="simple_question"):
        answer, used = llm_client._chat_completion_with_usage([{"role": "user", "content": "hello"}], max_tokens=800)
    assert answer == "ok" and used["total_tokens"] == 1500
    [(status, consumed, cost, prov, _op, _est, measured, _key)] = _ledger(sys_conn, tenant)
    # 1,000 x $0.000002 + 500 x $0.000008 = $0.006 = 0.6 credits
    assert (status, cost, consumed, prov) == ("consumed", Decimal("0.006"), Decimal("0.6"), provider)
    assert measured == {"input_token": 1000, "output_token": 500}


def test_an_empty_answer_retry_is_billed_too(sys_conn, ai, monkeypatch):
    llm_client, _ = ai
    tenant = _company(sys_conn, "starter")
    replies = [_Response(200, {"choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                               "usage": {"prompt_tokens": 100, "completion_tokens": 400, "total_tokens": 500}}),
               _answer(prompt=100, completion=300)]
    monkeypatch.setattr(llm_client, "_post_with_retry", lambda *a, **k: replies.pop(0))
    with credits.metering(tenant, "assistant_question"):
        _, used = llm_client._chat_completion_with_usage([{"role": "user", "content": "q"}], max_tokens=400)
    assert used["total_tokens"] == 900
    assert [row[0] for row in _ledger(sys_conn, tenant)] == ["consumed", "consumed"]


def test_ai_error_responses_are_not_charged(sys_conn, ai, monkeypatch):
    llm_client, _ = ai
    tenant = _company(sys_conn, "starter")
    monkeypatch.setattr(llm_client, "_post_with_retry", lambda *a, **k: _Response(503, {"error": "busy"}))
    with credits.metering(tenant, "assistant_question"):
        with pytest.raises(llm_client.LLMError):
            llm_client._chat_completion_with_usage([{"role": "user", "content": "q"}], max_tokens=100)
    assert [row[0] for row in _ledger(sys_conn, tenant)] == ["released"]
    assert _balance(sys_conn, tenant, "ai") == (Decimal("0"), Decimal("0"))


def test_an_unpriced_model_is_never_called(sys_conn, monkeypatch):
    from src.ai.rag import llm_client

    tenant = _company(sys_conn, "starter")
    monkeypatch.setattr(llm_client, "active_provider", lambda: f"unpriced_{uuid.uuid4().hex[:6]}")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    calls = []
    monkeypatch.setattr(llm_client, "_post_with_retry", lambda *a, **k: calls.append(1) or _answer())
    with credits.metering(tenant, "assistant_question"):
        with pytest.raises(credits.BudgetError) as refused:
            llm_client._chat_completion_with_usage([{"role": "user", "content": "q"}], max_tokens=100)
    assert refused.value.reason == "COST_NOT_CONFIGURED" and calls == []


def test_ai_request_size_and_concurrency_limits(sys_conn, ai, monkeypatch):
    llm_client, provider = ai
    tenant = _company(sys_conn, "enterprise")
    with credits.metering(tenant, "assistant_question"):
        with pytest.raises(credits.BudgetError) as too_large:
            credits.reserve("ai", provider, "m", {"input_token": 10, "output_token": 1_000_000})
        assert too_large.value.reason == "REQUEST_TOO_LARGE"
        for _ in range(3):                             # max_ai_concurrency = 3 calls in flight
            credits.reserve("ai", provider, "m", {"input_token": 10, "output_token": 10})
        with pytest.raises(credits.BudgetError) as busy:
            credits.reserve("ai", provider, "m", {"input_token": 10, "output_token": 10})
    assert busy.value.reason == "CONCURRENCY_LIMIT" and busy.value.status_code == 429


def test_ai_and_data_budgets_are_separate(sys_conn, ai, monkeypatch):
    llm_client, _ = ai
    tenant = _company(sys_conn, "starter")
    admin.adjust_credits(sys_conn, tenant_id=tenant, budget_kind="data", credits_delta=Decimal("436"),
                         reference="use-all-data", approved_by="test", reason="test")
    sys_conn.commit()
    monkeypatch.setattr(llm_client, "_post_with_retry", lambda *a, **k: _answer())
    with credits.metering(tenant, "assistant_question"):
        llm_client._chat_completion_with_usage([{"role": "user", "content": "q"}], max_tokens=100)  # AI still works


# --- data path ---------------------------------------------------------------------

def test_paid_data_requests_are_metered_and_free_ones_are_not(sys_conn, monkeypatch):
    from src.market_scraper import provider_billing

    tenant = _company(sys_conn, "starter")
    assert provider_billing.classify("https://overpass-api.de/api/interpreter") is None
    assert provider_billing.classify("https://www.googleapis.com/youtube/v3/search") is None
    assert provider_billing.classify("https://maps.googleapis.com/maps/api/place/textsearch/json")[0] == "google_places"
    assert provider_billing.classify("https://maps.googleapis.com/maps/api/geocode/json")[0] == "google_geocoding"
    assert provider_billing.classify("https://unknown.example/api")[0].startswith("unlisted:")

    assert provider_billing.metered_request("https://overpass-api.de/api/interpreter", lambda: {"free": True}) == {"free": True}
    sent = []
    with credits.metering(tenant, "market_discovery"):
        with pytest.raises(credits.BudgetError):  # Google Places has no confirmed price on this server
            provider_billing.metered_request("https://places.googleapis.com/v1/places:searchText?key=SECRET",
                                             lambda: sent.append(1))
        with pytest.raises(credits.BudgetError):  # an unknown service is never free by default
            provider_billing.metered_request("https://unknown.example/api", lambda: sent.append(1))
    assert sent == []


def test_request_json_spends_data_credits_and_ledger_holds_no_secrets(sys_conn, monkeypatch):
    from src.market_scraper import provider_billing
    from src.market_scraper.market_discovery import http

    tenant = _company(sys_conn, "starter")
    provider = _provider(sys_conn, usd="0.03")
    monkeypatch.setitem(provider_billing._PAID, ("paid.example", "/"), (provider, "op", "request"))
    monkeypatch.setattr(http, "_cache", lambda: None)

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def request(self, *a, **k):
            return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: {"results": [1]}})()

    monkeypatch.setattr(http.httpx, "Client", _Client)
    with credits.metering(tenant, "market_discovery"):
        assert http.request_json("GET", "https://paid.example/search", params={"key": "SECRET-API-KEY"}) == {"results": [1]}
    rows = _ledger(sys_conn, tenant)
    assert [r[0] for r in rows] == ["consumed"] and rows[0][1] == Decimal("3")
    assert "SECRET" not in str(rows)


def test_worker_threads_keep_the_company_context(sys_conn):
    from concurrent.futures import ThreadPoolExecutor

    tenant = _company(sys_conn, "starter")
    with credits.metering(tenant, "market_discovery"):
        with ThreadPoolExecutor(max_workers=4) as pool:
            seen = list(pool.map(credits.bind(lambda _: credits.current().tenant_id), range(8)))
        with ThreadPoolExecutor(max_workers=2) as pool:
            unbound = list(pool.map(lambda _: credits.current(), range(2)))
    assert seen == [tenant] * 8 and unbound == [None, None]

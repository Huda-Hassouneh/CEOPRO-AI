"""
One real, tiny AI call through the metered path - only when explicitly
enabled with real credentials and a confirmed price. Skipped (and reported
as skipped) otherwise; never part of ordinary CI.

    KEEL_LIVE_PROVIDER_SMOKE=1 GROQ_API_KEY=... \
    KEEL_SMOKE_INPUT_USD_PER_MILLION=<confirmed> KEEL_SMOKE_OUTPUT_USD_PER_MILLION=<confirmed> \
    AI_TEST_DATABASE_URL=... pytest src/ai/tests/test_provider_smoke_live.py

At most 16 output tokens, under a $0.01 provider cap: a failure can't spend more.
"""
import os
import uuid
from datetime import date
from decimal import Decimal

import psycopg2
import pytest

_MISSING = [name for name in ("KEEL_LIVE_PROVIDER_SMOKE", "GROQ_API_KEY", "AI_TEST_DATABASE_URL",
                              "KEEL_SMOKE_INPUT_USD_PER_MILLION", "KEEL_SMOKE_OUTPUT_USD_PER_MILLION") if not os.getenv(name)]
pytestmark = pytest.mark.skipif(bool(_MISSING), reason=f"live provider smoke test not enabled (missing: {', '.join(_MISSING)})")


def test_one_real_groq_call_is_metered(monkeypatch):
    from src.ai.billing import admin, credits
    from src.ai.rag import llm_client

    monkeypatch.delenv("KEEL_TEST_DISABLE_METERING", raising=False)
    conn = psycopg2.connect(os.environ["AI_TEST_DATABASE_URL"])
    tenant = str(uuid.uuid4())
    provider = f"smoke_{uuid.uuid4().hex[:6]}"
    try:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, 'Smoke', 'JO', 'JOD');",
                           (tenant,))
            cursor.execute("INSERT INTO tenant_plan_assignments (tenant_id, plan_key, status) VALUES (%s, 'starter', 'active');", (tenant,))
        for unit, setting in (("input_token", "KEEL_SMOKE_INPUT_USD_PER_MILLION"), ("output_token", "KEEL_SMOKE_OUTPUT_USD_PER_MILLION")):
            admin.set_price(conn, budget_kind="ai", provider=provider, operation="*", unit=unit,
                            unit_cost_usd=Decimal(os.environ[setting]) / Decimal(1_000_000), source="smoke test",
                            verified_on=date.today(), approved_by="smoke test", reason="live smoke test")
        admin.set_control(conn, provider=provider, approved_by="smoke test", reason="smoke cap", monthly_cap_usd=Decimal("0.01"))
        conn.commit()
        monkeypatch.setattr(llm_client, "active_provider", lambda: provider)
        with credits.metering(tenant, "smoke_test"):
            answer, used = llm_client._chat_completion_with_usage([{"role": "user", "content": "Reply with OK."}], max_tokens=16)
        assert used["total_tokens"] > 0
        with conn.cursor() as cursor:
            cursor.execute("SELECT status, actual_cost_usd FROM usage_ledger WHERE tenant_id = %s;", (tenant,))
            rows = cursor.fetchall()
        assert rows and all(status == "consumed" and cost < Decimal("0.01") for status, cost in rows)
    finally:
        conn.rollback()
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM companies WHERE tenant_id = %s;", (tenant,))
        conn.commit()
        conn.close()

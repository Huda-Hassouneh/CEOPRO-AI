"""
The exact per-question records (rag/business_records.py, advisor._records)
against a real PostgreSQL database, as the restricted ceopro_app role with
row-level security (skipped unless AI_TEST_DATABASE_URL and APP_DB_PASSWORD
are set). The model's reply is scripted; what is checked is what reaches it:
the figures for exactly the period and product asked about, nothing from
another company, nothing a role may not see, and an honest "no records" for
a period without sales.
"""
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import psycopg2
import pytest

from src.ai.rag import advisor, pipeline
from src.ai.tests.test_rag_advisor_integration_db import ADMIN_DATABASE_URL, APP_DB_PASSWORD, _app_conn
from src.ai.tests.test_rls_integration_db import _insert_user

pytestmark = pytest.mark.skipif(
    not ADMIN_DATABASE_URL or not APP_DB_PASSWORD,
    reason="AI_TEST_DATABASE_URL and/or APP_DB_PASSWORD not set - skipping live-DB integration test",
)

# March 2024 (three invoices) and February 2024 (one): far enough back that "today" never overlaps them.
INVOICES = [  # (issue date, total, units of the oil, units of the honey)
    (datetime(2024, 3, 2, 10, tzinfo=timezone.utc), "120.500", 10, 1),
    (datetime(2024, 3, 15, 10, tzinfo=timezone.utc), "60.000", 4, 2),
    (datetime(2024, 3, 30, 10, tzinfo=timezone.utc), "19.500", 0, 1),
    (datetime(2024, 2, 10, 10, tzinfo=timezone.utc), "80.000", 5, 0),
]


@pytest.fixture
def shop():
    admin = psycopg2.connect(ADMIN_DATABASE_URL)
    admin.autocommit = True
    cursor = admin.cursor()
    tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
    for tenant_id, name in [(tenant_a, "Records Test Foods"), (tenant_b, "Records Test Other")]:
        cursor.execute("INSERT INTO companies (tenant_id, business_name, business_type, country_code, primary_currency, "
                       "city) VALUES (%s, %s, 'grocery', 'JO', 'JOD', 'Amman');", (tenant_id, name))
    for role in ("owner", "staff"):
        cursor.execute("INSERT INTO system_roles (role_key, role_name) VALUES (%s, %s) ON CONFLICT DO NOTHING;", (role, role))
    owner_a, staff_a, owner_b = (_insert_user(cursor, f"rec-{label}") for label in ("owner-a", "staff-a", "owner-b"))
    for tenant_id, user_id, role in [(tenant_a, owner_a, "owner"), (tenant_a, staff_a, "staff"), (tenant_b, owner_b, "owner")]:
        cursor.execute("INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, %s);", (tenant_id, user_id, role))
    oil, honey = str(uuid.uuid4()), str(uuid.uuid4())
    cursor.execute("INSERT INTO products (product_id, tenant_id, product_name, current_price, cost_price, currency) VALUES "
                   "(%s, %s, %s, 9.500, 6.200, 'JOD'), (%s, %s, %s, 19.500, 12.500, 'JOD');",
                   (oil, tenant_a, json.dumps({"en": "Extra Virgin Olive Oil 1L", "ar": "زيت زيتون بكر ممتاز 1 لتر"}),
                    honey, tenant_a, json.dumps({"en": "Sidr Honey 500g", "ar": "عسل سدر 500 غرام"})))
    cursor.execute("INSERT INTO inventory (tenant_id, product_id, stock_quantity, reorder_level) VALUES (%s, %s, 37, 10);",
                   (tenant_a, oil))
    for n, (issued, total, oil_units, honey_units) in enumerate(INVOICES):
        invoice = str(uuid.uuid4())
        cursor.execute("INSERT INTO invoices (invoice_id, tenant_id, invoice_number, issue_date, subtotal, total_amount, "
                       "currency, customer_name) VALUES (%s, %s, %s, %s, %s, %s, 'JOD', %s);",
                       (invoice, tenant_a, f"REC-{n}", issued, total, total, "Hotel Alpha" if n == 0 else "Cafe Beta"))
        for product, units, price in ((oil, oil_units, "9.500"), (honey, honey_units, "19.500")):
            if units:
                cursor.execute("INSERT INTO invoice_items (tenant_id, invoice_id, product_id, quantity, unit_price, "
                               "total_price) VALUES (%s, %s, %s, %s, %s, %s);",
                               (tenant_a, invoice, product, units, price, Decimal(price) * units))
    for tenant_id in (tenant_a, tenant_b):
        pipeline.invalidate_tenant_index_cache(tenant_id)
    yield {"tenant_a": tenant_a, "tenant_b": tenant_b, "owner_a": owner_a, "staff_a": staff_a, "owner_b": owner_b}
    for tenant_id in (tenant_a, tenant_b):
        for table in ("invoice_items", "invoices", "inventory", "products", "conversation_sessions"):
            cursor.execute(f"DELETE FROM {table} WHERE tenant_id = %s;", (tenant_id,))
        cursor.execute("DELETE FROM companies WHERE tenant_id = %s;", (tenant_id,))
    admin.close()


@pytest.fixture
def prompts(monkeypatch):
    seen = []

    def call(messages, usage, max_tokens=None):
        seen.append(messages[-1]["content"])
        return json.dumps({"blocks": [{"type": "paragraph", "claims": [
            {"text": "Here is what the records show.", "kind": "general", "evidence": []}]}]})
    monkeypatch.setattr(advisor, "_call", call)
    return seen


def _ask(shop, prompts, question, who="owner_a", tenant="tenant_a", state=None):
    conn = _app_conn(shop[tenant], shop[who])
    try:
        result = advisor.answer(conn, shop[tenant], question, user_id=shop[who], state=state, enable_research=False)
    finally:
        conn.close()
    return result, prompts[-1]


def test_a_named_month_gets_that_months_exact_sales_and_the_month_before(shop, prompts):
    _, prompt = _ask(shop, prompts, "How much did we sell in March 2024?")
    # 120.5 + 60 + 19.5 = 200 JOD from 3 invoices; February: 80 JOD from 1 invoice (+150%).
    assert "Revenue 200 JOD from 3 invoices in March 2024" in prompt
    assert "February 2024 (2024-02-01 to 2024-02-29): 80 JOD from 1 invoices, a change of +150.0%" in prompt
    assert "Periods asked about: March 2024 = 2024-03-01 to 2024-03-31" in prompt


def test_arabic_month_and_a_named_product(shop, prompts):
    _, prompt = _ask(shop, prompts, "كم بعنا من زيت الزيتون في آذار 2024؟")
    # 10 + 4 units at 9.5 = 133 JOD, on 2 invoices; February: 5 units.
    assert "زيت زيتون بكر ممتاز 1 لتر: 14 units sold for 133 JOD on 2 invoices in March 2024" in prompt
    assert "February 2024: 5 units" in prompt


def test_rankings_by_units_and_by_revenue_and_customers(shop, prompts):
    _, prompt = _ask(shop, prompts, "Who were my top customers in March 2024 and what sold the most units?")
    assert "#1 Extra Virgin Olive Oil 1L: 14 units (133 JOD) in March 2024" in prompt
    assert "#1 Hotel Alpha: 120.5 JOD from 1 invoices" in prompt


def test_two_periods_are_compared_side_by_side(shop, prompts):
    _, prompt = _ask(shop, prompts, "Compare March 2024 with February 2024")
    assert "March 2024: 200 JOD (3 invoices) vs February 2024: 80 JOD (1 invoices); difference 120 JOD (+150.0%" in prompt


def test_a_follow_up_changes_only_the_period(shop, prompts):
    first, _ = _ask(shop, prompts, "What were my sales in March 2024?")
    _, prompt = _ask(shop, prompts, "and in February 2024?", state=first["state"])
    assert "Revenue 80 JOD from 1 invoices in February 2024" in prompt


def test_a_period_without_sales_says_so_with_the_dates_the_records_cover(shop, prompts):
    _, prompt = _ask(shop, prompts, "How much did we sell in March 2023?")
    assert "no sales are recorded in this period. Your sales records run from 2024-02-10 to 2024-03-30." in prompt
    assert "Revenue 0" not in prompt  # never a zero presented as a result


def test_a_products_stock_with_its_sales_pace_only_for_roles_that_may_see_sales(shop, prompts):
    _, owner = _ask(shop, prompts, "What is the stock level of Extra Virgin Olive Oil 1L?")
    assert "Stock of Extra Virgin Olive Oil 1L" in owner and "37 units in stock" in owner and "reorder level 10" in owner
    _, staff = _ask(shop, prompts, "What is the stock level of Extra Virgin Olive Oil 1L?", who="staff_a")
    assert "37 units in stock" in staff
    assert "units sold" not in staff and "days of stock" not in staff


def test_staff_get_no_sales_figures_and_are_told_why(shop, prompts):
    result, prompt = _ask(shop, prompts, "How much did we sell in March 2024?", who="staff_a")
    assert "200" not in prompt and "120.5" not in prompt
    assert any(s["need"] == "sales" and s["status"] == "not_permitted" for s in result["evidence_status"])


def test_another_company_never_sees_these_figures(shop, prompts):
    _, prompt = _ask(shop, prompts, "How much did we sell in March 2024?", who="owner_b", tenant="tenant_b")
    assert "200 JOD" not in prompt and "Hotel Alpha" not in prompt and "Olive Oil" not in prompt
    assert "no sales are recorded" in prompt

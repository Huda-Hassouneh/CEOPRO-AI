"""
Integration tests for dashboard/reports.py against a real PostgreSQL
instance. Same convention as every other live-DB test in this package:
skipped unless AI_TEST_DATABASE_URL is set.
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

from src.ai.dashboard.reports import get_sales_report, iter_sales_rows

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


def _insert_company(conn) -> str:
    tenant_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, %s, 'JO', 'JOD');",
            (tenant_id, f"Test Co {tenant_id[:8]}"),
        )
    return tenant_id


def _insert_product(conn, tenant_id, name="Widget", cost_price=None) -> str:
    product_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, cost_price, currency) "
            "VALUES (%s, %s, %s, 10.0, %s, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name}), cost_price),
        )
    return product_id


def _insert_invoice(conn, tenant_id, product_id, quantity, unit_price, issue_date, customer_name=None):
    invoice_id = str(uuid.uuid4())
    total = quantity * unit_price
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO invoices (invoice_id, tenant_id, invoice_number, customer_name, issue_date, subtotal, total_amount, currency) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'JOD');",
            (invoice_id, tenant_id, f"INV-{invoice_id[:8]}", customer_name, issue_date, total, total),
        )
        cursor.execute(
            "INSERT INTO invoice_items (tenant_id, invoice_id, product_id, quantity, unit_price, total_price) "
            "VALUES (%s, %s, %s, %s, %s, %s);",
            (tenant_id, invoice_id, product_id, quantity, unit_price, total),
        )
    return invoice_id


def test_returns_honest_empty_report_for_a_brand_new_tenant(conn):
    tenant_id = _insert_company(conn)
    conn.commit()

    result = get_sales_report(conn, tenant_id)

    assert result["rows"] == []
    assert result["returned_row_count"] == 0
    assert result["total_row_count"] == 0
    assert result["truncated"] is False


def test_report_row_reflects_a_real_invoice_line_item(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, name="Widget", cost_price=4.0)
    conn.commit()
    now = datetime.now(timezone.utc)
    _insert_invoice(conn, tenant_id, product_id, quantity=3, unit_price=10.0, issue_date=now, customer_name="Acme")
    conn.commit()

    result = get_sales_report(conn, tenant_id)

    assert result["returned_row_count"] == 1
    row = result["rows"][0]
    assert row["product_name"] == "Widget"
    assert row["customer_name"] == "Acme"
    assert row["quantity"] == 3
    assert row["unit_price"] == 10.0
    assert row["total_price"] == 30.0
    assert row["has_cost_data"] is True
    assert row["line_gross_profit"] == pytest.approx(18.0)  # (10 - 4) * 3


def test_line_gross_profit_is_never_fabricated_when_cost_price_is_unset(conn):
    """The core honesty requirement: a missing cost_price must yield a
    null gross profit, never a silently-assumed-zero-cost inflated
    number."""
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, name="Mystery Item", cost_price=None)
    conn.commit()
    _insert_invoice(conn, tenant_id, product_id, quantity=2, unit_price=15.0, issue_date=datetime.now(timezone.utc))
    conn.commit()

    result = get_sales_report(conn, tenant_id)

    row = result["rows"][0]
    assert row["has_cost_data"] is False
    assert row["line_gross_profit"] is None
    assert row["total_price"] == 30.0  # revenue is still real and reported


def test_date_range_filters_rows(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id)
    conn.commit()
    now = datetime.now(timezone.utc)
    _insert_invoice(conn, tenant_id, product_id, quantity=1, unit_price=10.0, issue_date=now - timedelta(days=40))
    _insert_invoice(conn, tenant_id, product_id, quantity=1, unit_price=10.0, issue_date=now - timedelta(days=2))
    conn.commit()

    result = get_sales_report(conn, tenant_id, start_date=now - timedelta(days=10), end_date=now + timedelta(days=1))

    assert result["returned_row_count"] == 1
    assert result["total_row_count"] == 1


def test_rows_are_ordered_most_recent_first(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id)
    conn.commit()
    now = datetime.now(timezone.utc)
    _insert_invoice(conn, tenant_id, product_id, quantity=1, unit_price=1.0, issue_date=now - timedelta(days=20))
    _insert_invoice(conn, tenant_id, product_id, quantity=1, unit_price=2.0, issue_date=now - timedelta(days=1))
    conn.commit()

    result = get_sales_report(conn, tenant_id)

    assert [row["unit_price"] for row in result["rows"]] == [2.0, 1.0]


def test_limit_truncates_and_reports_it_honestly(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id)
    conn.commit()
    now = datetime.now(timezone.utc)
    for i in range(3):
        _insert_invoice(conn, tenant_id, product_id, quantity=1, unit_price=1.0, issue_date=now - timedelta(days=i))
    conn.commit()

    result = get_sales_report(conn, tenant_id, limit=2)

    assert result["returned_row_count"] == 2
    assert result["total_row_count"] == 3
    assert result["truncated"] is True


def test_only_this_tenants_own_invoices_are_included(conn):
    tenant_a = _insert_company(conn)
    tenant_b = _insert_company(conn)
    product_a = _insert_product(conn, tenant_a)
    product_b = _insert_product(conn, tenant_b)
    conn.commit()
    now = datetime.now(timezone.utc)
    _insert_invoice(conn, tenant_a, product_a, quantity=1, unit_price=10.0, issue_date=now)
    _insert_invoice(conn, tenant_b, product_b, quantity=1, unit_price=99.0, issue_date=now)
    conn.commit()

    result = get_sales_report(conn, tenant_a)

    assert result["returned_row_count"] == 1
    assert result["rows"][0]["total_price"] == 10.0


def test_pages_cover_every_row_exactly_once(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id)
    conn.commit()
    same_day = datetime.now(timezone.utc).replace(microsecond=0)
    # Several lines share a date, so only the tie-breaker keeps pages stable.
    for i in range(7):
        _insert_invoice(conn, tenant_id, product_id, quantity=1, unit_price=float(i + 1),
                        issue_date=same_day - timedelta(days=i // 3))
    conn.commit()

    pages = [get_sales_report(conn, tenant_id, limit=3, offset=offset) for offset in (0, 3, 6)]

    seen = [row["invoice_id"] for page in pages for row in page["rows"]]
    assert len(seen) == 7 and len(set(seen)) == 7
    assert [page["truncated"] for page in pages] == [True, True, False]
    assert all(page["total_row_count"] == 7 for page in pages)
    assert get_sales_report(conn, tenant_id, limit=3, offset=9)["rows"] == []


def test_export_iterator_returns_the_whole_period_in_page_order(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id)
    conn.commit()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    for i in range(11):
        _insert_invoice(conn, tenant_id, product_id, quantity=1, unit_price=float(i + 1),
                        issue_date=now - timedelta(days=i // 4))
    conn.commit()

    exported = list(iter_sales_rows(conn, tenant_id, batch_size=4))   # several batches, ties across batch edges
    paged = get_sales_report(conn, tenant_id, limit=100)["rows"]

    assert [row["invoice_id"] for row in exported] == [row["invoice_id"] for row in paged]
    assert len(exported) == 11


def test_pdf_report_totals_months_and_products_from_real_rows(conn):
    from src.ai.dashboard import sales_pdf

    tenant_id = _insert_company(conn)
    oil = _insert_product(conn, tenant_id, "Olive Oil", cost_price=6.0)
    dates = _insert_product(conn, tenant_id, "Dates")  # no cost price
    _insert_invoice(conn, tenant_id, oil, 2, 10.0, datetime(2026, 8, 15, tzinfo=timezone.utc))
    _insert_invoice(conn, tenant_id, oil, 1, 10.0, datetime(2026, 9, 2, tzinfo=timezone.utc))
    _insert_invoice(conn, tenant_id, dates, 4, 5.0, datetime(2026, 9, 3, tzinfo=timezone.utc))

    data = sales_pdf.report_data(conn, tenant_id, None, None)
    [totals] = data["totals"]
    assert (totals["currency"], totals["lines"], float(totals["revenue"])) == ("JOD", 3, 50.0)
    assert float(totals["gross_profit"]) == 12.0 and float(totals["revenue_with_cost"]) == 30.0
    assert [(m["month"], float(m["revenue"])) for m in data["monthly"]] == [("2026-09", 30.0), ("2026-08", 20.0)]
    assert [p["product"] for p in data["top"]] == ["Olive Oil", "Dates"]
    assert data["total_lines"] == 3 and len(data["recent"]) == 3

    september = sales_pdf.report_data(conn, tenant_id, datetime(2026, 9, 1, tzinfo=timezone.utc), datetime(2026, 10, 1, tzinfo=timezone.utc))
    assert september["total_lines"] == 2

    for lang in ("en", "ar"):
        pdf = sales_pdf.render_pdf(data, lang)
        assert pdf.startswith(b"%PDF") and b"/Type /Page" in pdf

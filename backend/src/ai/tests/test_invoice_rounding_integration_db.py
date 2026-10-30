"""Exact paid totals across the existing canonical invoice writers and retries."""
import io
import os
from decimal import Decimal
from uuid import uuid4

import psycopg2
import pytest
from openpyxl import Workbook

from src.ai.extraction import promotion
from src.ai.sales.quick_sale import record_quick_sale
from src.ai.tests.test_extraction_promotion_integration_db import (
    conn, seeded_tenant, _run_with_discount_columns, _template_row,
)
from src.ai.tests.test_sales_quick_sale_integration_db import _insert_company, _insert_product
from src.ai.tests.test_products_integration_db import seeded_tenants
from src.ai.tests.test_structured_business_integration_db import setup, seed, preview, review, confirm, query

pytestmark = pytest.mark.skipif(not os.getenv("AI_TEST_DATABASE_URL"), reason="Native PostgreSQL required")


@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize("quantity,price,discount,paid,adjustment", [
    ("3", "5.75", "10", "15.53", "-0.0001"),
    ("912.35", "1.012", "5", "877.135", "0.00171"),
    ("1.2345", "1.2345", "0", "1.5240", "0.00000975"),
    ("0.4", "12.3456", "0", "4.9382", "0"),
])
def test_exact_import_residual_in_bulk_fallback_and_duplicate_retry(
        conn, seeded_tenant, monkeypatch, fallback, quantity, price, discount, paid, adjustment):
    tenant, actor, job = seeded_tenant
    if fallback:
        def interrupted_batch(*args):
            raise RuntimeError("Synthetic interrupted invoice batch")
        monkeypatch.setattr(promotion, "_insert_invoices_mirror_batch", interrupted_batch)
    rows = [_template_row(quantity=quantity, unit_price=price, discount_pct=discount, amount_raw=paid)]
    _, result = _run_with_discount_columns(conn, tenant, job, actor, rows)
    conn.commit()
    assert (result.rows_promoted, result.rows_failed) == (1, 0)
    with conn.cursor() as c:
        c.execute("SELECT quantity,unit_price,total_price,rounding_adjustment FROM invoice_items WHERE tenant_id=%s", (tenant,))
        q, unit, total, residual = c.fetchone()
        assert q == Decimal(quantity) and total == Decimal(paid) and residual == Decimal(adjustment)
        assert total == q * unit + residual and abs(residual) <= q * Decimal("0.00005")
        if quantity == "0.4":
            assert unit == Decimal("12.3455")
        c.execute("SELECT current_price FROM products WHERE tenant_id=%s", (tenant,))
        assert c.fetchone() == (Decimal(price),)  # original source price preserved
        c.execute("SELECT subtotal,tax_amount,total_amount,currency,payment_status FROM invoices WHERE tenant_id=%s", (tenant,))
        assert c.fetchone() == (Decimal(paid), Decimal(0), Decimal(paid), "JOD", "PAID")
        c.execute("SELECT total_price,original_currency FROM transactions WHERE tenant_id=%s", (tenant,))
        assert c.fetchall() == [(Decimal(paid), "JOD")]
        retry_job = str(uuid4())
        c.execute("INSERT INTO ingestion_jobs(job_id,tenant_id,source_id,job_status) SELECT %s,tenant_id,source_id,'PROCESSING' FROM ingestion_jobs WHERE job_id=%s", (retry_job, job))
    _, replay = _run_with_discount_columns(conn, tenant, retry_job, actor, rows)
    conn.commit()
    assert (replay.rows_promoted, replay.rows_duplicate, replay.rows_failed) == (0, 1, 0)
    with conn.cursor() as c:
        for table in ("invoice_items", "invoices", "transactions"):
            c.execute(f"SELECT count(*) FROM {table} WHERE tenant_id=%s", (tenant,))
            assert c.fetchone() == (1,)
        with pytest.raises(psycopg2.errors.CheckViolation):
            c.execute("UPDATE invoice_items SET total_price=quantity*unit_price+1,rounding_adjustment=1 WHERE tenant_id=%s", (tenant,))
    conn.rollback()
    if Decimal(adjustment) != 0:
        with conn.cursor() as c:
            with pytest.raises(psycopg2.errors.CheckViolation):
                c.execute("UPDATE invoice_items SET rounding_adjustment=0 WHERE tenant_id=%s", (tenant,))
        conn.rollback()


def test_quick_sale_keeps_existing_total_and_exact_fractional_residual(conn):
    tenant = _insert_company(conn)
    product = _insert_product(conn, tenant, "Synthetic fractional sale", current_price=Decimal("1.2345"))
    result = record_quick_sale(conn, tenant, None, product, Decimal("1.2345"))
    conn.commit()
    assert result["total_amount"] == 1.524 and result["currency"] == "JOD"
    with conn.cursor() as c:
        c.execute("SELECT i.total_amount,i.tax_amount,ii.total_price,ii.rounding_adjustment FROM invoices i JOIN invoice_items ii USING(tenant_id,invoice_id) WHERE i.invoice_id=%s", (result["invoice_id"],))
        assert c.fetchone() == (Decimal("1.5240"), Decimal(0), Decimal("1.5240"), Decimal("0.00000975"))


@pytest.mark.parametrize("status", ["PAID", "UNPAID"])
def test_structured_invoice_preserves_tax_currency_payment_state_and_replay(setup, status):
    from src.ai.extraction.structured_business import HEADERS
    client, app, tenants, actors = setup
    seed(setup)
    book = Workbook()
    headers = book.active
    headers.title = "Invoices"
    headers.append(HEADERS["Invoices"])
    number = "ROUND-" + uuid4().hex
    headers.append([number, "Synthetic Customer", "2026-10-26", "2026-11-01", 1.524, .1524, 1.6764, "JOD", status])
    items = book.create_sheet("Invoice Items")
    items.append(HEADERS["Invoice Items"])
    items.append([number, "", "", "REF-1", 1.2345, 1.2345])
    out = io.BytesIO()
    book.save(out)
    book.close()
    draft = preview(client, "invoices", out.getvalue(), "rounding.xlsx")
    reviewed = review(client, draft)
    response = confirm(client, draft, reviewed)
    assert response.status_code == 200, response.text
    assert confirm(client, draft, reviewed).json() == response.json()
    assert query(tenants[0], "SELECT subtotal,tax_amount,total_amount,currency,payment_status FROM invoices WHERE tenant_id=%s") == [(Decimal("1.524"), Decimal(".1524"), Decimal("1.6764"), "JOD", status)]
    assert query(tenants[0], "SELECT total_price,rounding_adjustment FROM invoice_items WHERE tenant_id=%s") == [(Decimal("1.524"), Decimal(".00000975"))]
    assert query(tenants[0], "SELECT count(*) FROM transactions WHERE tenant_id=%s") == [(1 if status == "PAID" else 0,)]
    assert query(tenants[0], "SELECT count(*) FROM audit_logs WHERE tenant_id=%s AND action_type='STRUCTURED_IMPORT_POSTED'") == [(1,)]

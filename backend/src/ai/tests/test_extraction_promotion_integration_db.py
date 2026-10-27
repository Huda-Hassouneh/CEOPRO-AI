"""
Integration tests for promotion.py against a real PostgreSQL instance -
same convention as test_extraction_ingestion_pipeline_integration_db.py:
skipped unless AI_TEST_DATABASE_URL is set. Proves the bulk (execute_values)
path and its SAVEPOINT-isolated batch/row fallback actually write correct
rows to products/transactions and correctly flag import_staging_rows -
the offline tests in test_extraction_promotion.py only cover the pure
eligibility-selection logic, not any SQL.
"""
import os
import uuid
from decimal import Decimal

import psycopg2
import pytest

from src.ai.extraction import ingestion_pipeline, promotion

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")

_TEMPLATE_HEADERS = ["product_name", "quantity", "unit_price", "currency", "transaction_date"]


def _template_row(**overrides):
    row = {
        "product_name": "Widget A", "quantity": "5", "unit_price": "19.99",
        "currency": "JOD", "transaction_date": "2026-08-30",
    }
    row.update(overrides)
    return row


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


@pytest.fixture
def seeded_tenant(conn):
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, 'Promotion QA Co', 'JO', 'JOD');",
            (tenant_id,),
        )
        cursor.execute(
            "INSERT INTO users (user_id, email, password_hash) VALUES (%s, %s, 'x');",
            (user_id, f"{user_id}@example.com"),
        )
        cursor.execute(
            "INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, 'owner');",
            (tenant_id, user_id),
        )
        cursor.execute(
            "INSERT INTO data_sources (source_id, tenant_id, source_name, source_type) "
            "VALUES (%s, %s, 'Test Source', 'CSV_UPLOAD');",
            (source_id, tenant_id),
        )
        cursor.execute(
            "INSERT INTO ingestion_jobs (job_id, tenant_id, source_id) VALUES (%s, %s, %s);",
            (job_id, tenant_id, source_id),
        )
    conn.commit()
    return tenant_id, user_id, job_id


def _staging_row(conn, staging_row_id):
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT validation_status, committed_table, committed_record_id "
            "FROM import_staging_rows WHERE staging_row_id = %s;",
            (staging_row_id,),
        )
        return cursor.fetchone()


def _product(conn, product_id):
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT product_name->>'en', current_price, currency, source, created_by_user_id "
            "FROM products WHERE product_id = %s;",
            (product_id,),
        )
        return cursor.fetchone()


def _transaction(conn, transaction_id):
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT product_id, quantity_sold, unit_price, total_price, original_currency "
            "FROM transactions WHERE transaction_id = %s;",
            (transaction_id,),
        )
        return cursor.fetchone()


def _invoice_items_for_tenant(conn, tenant_id):
    """Joins invoice_items -> invoices for this tenant - the mirror table
    pair the dashboard/RAG sales summary actually read (see
    promotion.py::_insert_invoices_mirror_batch's own docstring for why
    this mirror exists: a real bug found live in UAT where CSV-imported
    sales reached forecasting via `transactions` but never reached the
    Dashboard or chatbot, both of which only ever read invoices/
    invoice_items)."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT ii.product_id, ii.quantity, ii.unit_price, ii.total_price, "
            "i.currency, i.payment_status, i.total_amount, i.invoice_number "
            "FROM invoice_items ii JOIN invoices i "
            "ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id "
            "WHERE ii.tenant_id = %s ORDER BY i.invoice_number;",
            (tenant_id,),
        )
        return cursor.fetchall()


def _run(conn, tenant_id, job_id, user_id, rows):
    summary = ingestion_pipeline.process_records(
        tenant_id=tenant_id, job_id=job_id, source_name="f.csv", headers=_TEMPLATE_HEADERS, rows=rows, conn=conn,
    )
    return summary, promotion.promote_ingested_rows(conn, tenant_id, job_id, summary, user_id=user_id)


def _run_with_barcodes(conn, tenant_id, job_id, user_id, rows):
    summary = ingestion_pipeline.process_records(
        tenant_id=tenant_id, job_id=job_id, source_name="f.csv",
        headers=_TEMPLATE_HEADERS + ["barcode"], rows=rows, conn=conn,
    )
    return summary, promotion.promote_ingested_rows(conn, tenant_id, job_id, summary, user_id=user_id)


def test_complete_row_promotes_to_a_new_product_and_transaction(conn, seeded_tenant):
    tenant_id, user_id, job_id = seeded_tenant
    summary, promo = _run(conn, tenant_id, job_id, user_id, [_template_row()])
    conn.commit()

    assert promo.rows_promoted == 1
    assert promo.rows_skipped_incomplete == 0
    assert promo.rows_failed == 0
    assert promo.products_created == 1

    staging_row_id = summary.row_outcomes[0].staging_row_id
    status, committed_table, transaction_id = _staging_row(conn, staging_row_id)
    assert status == "COMMITTED"
    assert committed_table == "transactions"
    assert transaction_id is not None

    product_id, quantity, unit_price, total_price, currency = _transaction(conn, transaction_id)
    assert quantity == 5
    assert unit_price == Decimal("19.99")
    assert total_price == Decimal("99.9500")
    assert currency == "JOD"

    name, price, prod_currency, source, created_by = _product(conn, product_id)
    assert name == "Widget A"
    assert price == Decimal("19.99")
    assert prod_currency == "JOD"
    assert source == "IMPORTED"
    assert str(created_by) == user_id


def test_two_rows_same_product_name_share_one_product(conn, seeded_tenant):
    tenant_id, user_id, job_id = seeded_tenant
    rows = [_template_row(quantity="2"), _template_row(quantity="3", product_name="  widget a  ")]
    summary, promo = _run(conn, tenant_id, job_id, user_id, rows)
    conn.commit()

    assert promo.rows_promoted == 2
    assert promo.products_created == 1

    ids = []
    for outcome in summary.row_outcomes:
        _, _, txn_id = _staging_row(conn, outcome.staging_row_id)
        ids.append(txn_id)
    product_ids = {_transaction(conn, tid)[0] for tid in ids}
    assert len(product_ids) == 1


def test_existing_product_price_is_never_overwritten_by_a_later_import(conn, seeded_tenant):
    tenant_id, user_id, job_id = seeded_tenant
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (tenant_id, product_name, current_price, currency, source) "
            "VALUES (%s, %s::jsonb, 999.00, 'JOD', 'MANUAL') RETURNING product_id;",
            (tenant_id, '{"en": "Widget A"}'),
        )
        existing_product_id = cursor.fetchone()[0]
    conn.commit()

    summary, promo = _run(conn, tenant_id, job_id, user_id, [_template_row(unit_price="19.99")])
    conn.commit()

    assert promo.products_created == 0
    staging_row_id = summary.row_outcomes[0].staging_row_id
    _, _, transaction_id = _staging_row(conn, staging_row_id)
    product_id, _, _, _, _ = _transaction(conn, transaction_id)
    assert str(product_id) == str(existing_product_id)

    _, price, _, _, _ = _product(conn, existing_product_id)
    assert price == Decimal("999.00")  # untouched, even though the import's unit_price was 19.99


def test_product_identity_never_resolves_to_another_tenants_catalog(conn, seeded_tenant):
    tenant_id, user_id, job_id = seeded_tenant
    other_tenant_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, 'Other Product Owner', 'JO', 'JOD');", (other_tenant_id,),
        )
        cursor.execute(
            "INSERT INTO products (tenant_id, product_name, current_price, currency) "
            "VALUES (%s, '{\"en\": \"Shared Name\"}'::jsonb, 99, 'JOD');", (other_tenant_id,),
        )
    conn.commit()

    summary, result = _run(conn, tenant_id, job_id, user_id, [_template_row(product_name="Shared Name")])
    conn.commit()

    assert result.rows_promoted == 1 and result.products_created == 1
    _, _, transaction_id = _staging_row(conn, summary.row_outcomes[0].staging_row_id)
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT p.tenant_id FROM transactions t JOIN products p "
            "ON p.tenant_id=t.tenant_id AND p.product_id=t.product_id WHERE t.transaction_id=%s;",
            (transaction_id,),
        )
        assert str(cursor.fetchone()[0]) == tenant_id


def test_ambiguous_existing_name_is_held_while_independent_rows_promote(conn, seeded_tenant):
    tenant_id, user_id, job_id = seeded_tenant
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (tenant_id, product_name, current_price, currency, metadata) "
            "VALUES (%s, '{\"en\": \"Twin Product\"}'::jsonb, 10, 'JOD', '{\"sku\":\"A\"}'::jsonb), "
            "       (%s, '{\"en\": \"Twin Product\"}'::jsonb, 11, 'JOD', '{\"sku\":\"B\"}'::jsonb);",
            (tenant_id, tenant_id),
        )
    conn.commit()

    summary, result = _run(conn, tenant_id, job_id, user_id, [
        _template_row(product_name="Twin Product"),
        _template_row(product_name="Independent Product"),
    ])
    conn.commit()

    assert result.rows_promoted == 1
    assert result.rows_failed == 1
    assert result.products_created == 1
    assert result.errors[0]["status"] == "review_required"
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT validation_status, validation_errors, committed_record_id "
            "FROM import_staging_rows WHERE tenant_id=%s AND job_id=%s ORDER BY staging_row_id;",
            (tenant_id, job_id),
        )
        statuses = cursor.fetchall()
        cursor.execute("SELECT COUNT(*) FROM products WHERE tenant_id=%s AND product_name->>'en'='Twin Product';", (tenant_id,))
        twins = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM transactions WHERE tenant_id=%s;", (tenant_id,))
        transactions = cursor.fetchone()[0]
    assert statuses[0][0] == "PARTIAL"
    assert "multiple tenant products" in statuses[0][1]
    assert statuses[0][2] is None
    assert statuses[1][0] == "COMMITTED"
    assert twins == 2  # no third product was created for the ambiguous row
    assert transactions == 1


def test_name_and_barcode_that_point_to_different_products_are_held(conn, seeded_tenant):
    tenant_id, user_id, job_id = seeded_tenant
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (tenant_id, product_name, current_price, currency, metadata) "
            "VALUES (%s, '{\"en\": \"Name Match\"}'::jsonb, 10, 'JOD', '{\"barcode\":\"3017620422003\"}'::jsonb), "
            "       (%s, '{\"en\": \"Barcode Match\"}'::jsonb, 11, 'JOD', '{\"barcode\":\"96385074\"}'::jsonb);",
            (tenant_id, tenant_id),
        )
    conn.commit()

    summary, result = _run_with_barcodes(conn, tenant_id, job_id, user_id, [
        _template_row(product_name="Name Match", barcode="96385074"),
        _template_row(product_name="Independent Product", barcode=""),
    ])
    conn.commit()

    assert result.rows_promoted == 1
    assert result.rows_failed == 1
    assert result.errors[0]["status"] == "review_required"
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT validation_status, validation_errors, committed_record_id "
            "FROM import_staging_rows WHERE tenant_id=%s AND job_id=%s ORDER BY staging_row_id;",
            (tenant_id, job_id),
        )
        statuses = cursor.fetchall()
        cursor.execute("SELECT COUNT(*) FROM transactions WHERE tenant_id=%s;", (tenant_id,))
        transactions = cursor.fetchone()[0]
    assert statuses[0][0] == "PARTIAL"
    assert "identify different" in statuses[0][1]
    assert statuses[0][2] is None
    assert statuses[1][0] == "COMMITTED"
    assert transactions == 1


def test_row_missing_a_required_field_is_not_promoted_and_stays_unflagged(conn, seeded_tenant):
    tenant_id, user_id, job_id = seeded_tenant
    rows = [_template_row(unit_price="-5")]  # negative price -> dropped by validate_typed_fields()
    summary, promo = _run(conn, tenant_id, job_id, user_id, rows)
    conn.commit()

    assert promo.rows_promoted == 0
    assert promo.rows_skipped_incomplete == 1

    staging_row_id = summary.row_outcomes[0].staging_row_id
    status, committed_table, transaction_id = _staging_row(conn, staging_row_id)
    assert status == "PARTIAL"
    assert committed_table is None
    assert transaction_id is None


def test_promoted_transaction_is_mirrored_into_invoices_for_dashboard_and_rag(conn, seeded_tenant):
    tenant_id, user_id, job_id = seeded_tenant
    summary, promo = _run(conn, tenant_id, job_id, user_id, [_template_row()])
    conn.commit()
    assert promo.rows_promoted == 1

    rows = _invoice_items_for_tenant(conn, tenant_id)
    assert len(rows) == 1
    product_id, quantity, unit_price, total_price, currency, payment_status, total_amount, invoice_number = rows[0]
    assert quantity == 5
    assert unit_price == Decimal("19.99")
    assert total_price == Decimal("99.9500")
    assert currency == "JOD"
    assert payment_status == "PAID"
    assert total_amount == Decimal("99.9500")
    # Content-derived, not per-upload (IMPORT-<job>-<row> let a re-upload import every row again).
    assert invoice_number.startswith("IMP-") and len(invoice_number) == len("IMP-") + 32

    staging_row_id = summary.row_outcomes[0].staging_row_id
    _, _, transaction_id = _staging_row(conn, staging_row_id)
    txn_product_id, _, _, _, _ = _transaction(conn, transaction_id)
    assert str(product_id) == str(txn_product_id)  # same product on both sides of the mirror


def test_multi_batch_promotion_mirrors_every_row_into_invoices_too(conn, seeded_tenant, monkeypatch):
    """Same multi-batch-boundary proof as test_multi_batch_promotion_
    stitches_results_together, but for the invoices/invoice_items mirror -
    every batch's rows must land in both tables, not just the first."""
    monkeypatch.setattr(promotion, "_PROMOTION_BATCH_SIZE", 2)
    tenant_id, user_id, job_id = seeded_tenant
    rows = [_template_row(product_name=f"Widget {i}", quantity=str(i + 1)) for i in range(5)]
    summary, promo = _run(conn, tenant_id, job_id, user_id, rows)
    conn.commit()
    assert promo.rows_promoted == 5

    invoice_rows = _invoice_items_for_tenant(conn, tenant_id)
    assert len(invoice_rows) == 5
    assert sorted(r[1] for r in invoice_rows) == [1, 2, 3, 4, 5]  # quantities


def test_multi_batch_promotion_stitches_results_together(conn, seeded_tenant, monkeypatch):
    """Forces _PROMOTION_BATCH_SIZE down to 2 so a 5-row promotion spans
    three batches - proves `known` (the product cache) and the row/staging
    correlation both survive correctly across batch boundaries, not just
    within a single batch."""
    monkeypatch.setattr(promotion, "_PROMOTION_BATCH_SIZE", 2)
    tenant_id, user_id, job_id = seeded_tenant
    rows = [_template_row(product_name=f"Widget {i}", quantity=str(i + 1)) for i in range(5)]

    summary, promo = _run(conn, tenant_id, job_id, user_id, rows)
    conn.commit()

    assert promo.rows_promoted == 5
    assert promo.products_created == 5
    for i, outcome in enumerate(summary.row_outcomes):
        status, committed_table, transaction_id = _staging_row(conn, outcome.staging_row_id)
        assert status == "COMMITTED"
        _, quantity, _, _, _ = _transaction(conn, transaction_id)
        assert quantity == i + 1


# --- Discounted lines (first-customer acceptance finding) -------------------
# Every imported row used to be recorded at quantity x list price, ignoring the
# template's own discount_pct/amount_raw columns, so Dashboard revenue, reports
# and the RAG sales summary overstated what the business actually earned.

_DISCOUNT_HEADERS = _TEMPLATE_HEADERS + ["discount_pct", "amount_raw"]


def _run_with_discount_columns(conn, tenant_id, job_id, user_id, rows):
    summary = ingestion_pipeline.process_records(
        tenant_id=tenant_id, job_id=job_id, source_name="f.csv", headers=_DISCOUNT_HEADERS, rows=rows, conn=conn,
    )
    return summary, promotion.promote_ingested_rows(conn, tenant_id, job_id, summary, user_id=user_id)


def test_discounted_line_is_recorded_at_the_amount_actually_paid(conn, seeded_tenant):
    """The import template's own example row: 3 x 24.50 at 10% off, amount_raw 66.15."""
    tenant_id, user_id, job_id = seeded_tenant
    summary, promo = _run_with_discount_columns(conn, tenant_id, job_id, user_id, [
        _template_row(product_name="Premium Olive Oil 1L", quantity="3", unit_price="24.50", discount_pct="10", amount_raw="66.15"),
    ])
    conn.commit()
    assert promo.rows_promoted == 1

    _, quantity, unit_price, total_price, _, _, total_amount, _ = _invoice_items_for_tenant(conn, tenant_id)[0]
    assert (quantity, total_price, total_amount) == (3, Decimal("66.1500"), Decimal("66.1500"))
    assert unit_price == Decimal("22.0500")  # effective price paid, so quantity x unit_price == total

    _, _, transaction_id = _staging_row(conn, summary.row_outcomes[0].staging_row_id)
    _, quantity_sold, txn_unit_price, txn_total, _ = _transaction(conn, transaction_id)
    assert (quantity_sold, txn_unit_price, txn_total) == (3, Decimal("22.0500"), Decimal("66.1500"))


def test_discount_pct_alone_is_applied_when_no_paid_amount_is_given(conn, seeded_tenant):
    tenant_id, user_id, job_id = seeded_tenant
    _, promo = _run_with_discount_columns(conn, tenant_id, job_id, user_id, [
        _template_row(quantity="4", unit_price="10.00", discount_pct="25%", amount_raw=""),
    ])
    conn.commit()
    assert promo.rows_promoted == 1
    assert _invoice_items_for_tenant(conn, tenant_id)[0][3] == Decimal("30.0000")


def test_paid_amount_above_the_list_total_is_not_trusted_as_a_line_discount(conn, seeded_tenant):
    """A tax-inclusive or whole-order figure in amount_raw must not inflate one line."""
    tenant_id, user_id, job_id = seeded_tenant
    _, promo = _run_with_discount_columns(conn, tenant_id, job_id, user_id, [
        _template_row(quantity="2", unit_price="10.00", discount_pct="", amount_raw="250.00"),
    ])
    conn.commit()
    assert promo.rows_promoted == 1
    assert _invoice_items_for_tenant(conn, tenant_id)[0][3] == Decimal("20.0000")


def test_line_total_rules():
    def total(**fields):
        return promotion._line_total(fields, 3, Decimal("24.50"))
    assert total() == Decimal("73.5000")
    assert total(amount_raw="66.15") == Decimal("66.1500")
    assert total(discount_pct="10") == Decimal("66.1500")
    assert total(amount_raw="66.15", discount_pct="50") == Decimal("66.1500")  # paid amount wins
    assert total(amount_raw="0") == Decimal("73.5000")
    assert total(amount_raw="not-a-number", discount_pct="10") == Decimal("66.1500")
    assert total(discount_pct="150") == Decimal("73.5000")


def test_paid_total_not_divisible_by_quantity_still_satisfies_the_item_invariant(conn, seeded_tenant):
    """Found live: 3 x 5.75 at 10% off paid 15.53 - no exact 4-dp unit price exists, and
    invoice_items enforces total_price = quantity * unit_price. Every such row failed."""
    tenant_id, user_id, job_id = seeded_tenant
    _, promo = _run_with_discount_columns(conn, tenant_id, job_id, user_id, [
        _template_row(quantity="3", unit_price="5.75", discount_pct="10", amount_raw="15.53"),
    ])
    conn.commit()
    assert promo.rows_promoted == 1 and promo.rows_failed == 0
    _, quantity, unit_price, total_price, _, _, total_amount, _ = _invoice_items_for_tenant(conn, tenant_id)[0]
    # The money actually received is recorded exactly; the 4-dp unit price
    # reproduces it to within half a unit of its last decimal per item.
    assert total_price == total_amount == Decimal("15.53")
    assert unit_price == Decimal("5.1767")
    assert abs(total_price - quantity * unit_price) <= quantity * Decimal("0.00005")


def test_large_discounted_quantities_keep_the_exact_amount_paid(conn, seeded_tenant):
    """Found by reconciling dashboard revenue with the source exports: 900 kg
    at a 3-decimal JOD price with a 5% discount used to be snapped to the
    nearest 4-dp unit price, shifting revenue by up to 0.045 JOD per line."""
    tenant_id, user_id, job_id = seeded_tenant
    _, promo = _run_with_discount_columns(conn, tenant_id, job_id, user_id, [
        _template_row(product_name="Galvanized Sheet (kg)", quantity="912.35", unit_price="1.012", discount_pct="5", amount_raw="877.135"),
    ])
    conn.commit()
    assert promo.rows_promoted == 1
    _, quantity, unit_price, total_price, _, _, total_amount, _ = _invoice_items_for_tenant(conn, tenant_id)[0]
    assert total_price == total_amount == Decimal("877.135")


# --- Re-importing the same data (first-customer acceptance finding) ---------
# Uploading the same sales file twice used to import every row twice (1,597 ->
# 3,194 invoices), doubling Dashboard revenue.

def test_reimporting_the_same_rows_skips_them_as_duplicates(conn, seeded_tenant):
    tenant_id, user_id, job_id = seeded_tenant
    rows = [_template_row(quantity="2"), _template_row(product_name="Widget B", quantity="1", unit_price="5.00")]
    _, first = _run(conn, tenant_id, job_id, user_id, rows)
    conn.commit()
    assert (first.rows_promoted, first.rows_duplicate) == (2, 0)

    second_job = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO ingestion_jobs (job_id, tenant_id, source_id, job_status) "
            "SELECT %s, tenant_id, source_id, 'PROCESSING' FROM ingestion_jobs WHERE job_id = %s;",
            (second_job, job_id),
        )
    _, second = _run(conn, tenant_id, second_job, user_id, rows)
    conn.commit()
    assert (second.rows_promoted, second.rows_duplicate, second.rows_failed) == (0, 2, 0)
    assert len(_invoice_items_for_tenant(conn, tenant_id)) == 2


def test_identical_sales_on_the_same_day_in_one_file_are_both_kept(conn, seeded_tenant):
    """Two customers buying the same item at the same price on the same day are two sales."""
    tenant_id, user_id, job_id = seeded_tenant
    _, promo = _run(conn, tenant_id, job_id, user_id, [_template_row(quantity="1"), _template_row(quantity="1")])
    conn.commit()
    assert (promo.rows_promoted, promo.rows_duplicate) == (2, 0)
    assert len(_invoice_items_for_tenant(conn, tenant_id)) == 2


# --- fractional quantities --------------------------------------------------
# Found in first-customer acceptance testing: quantities were integers end to
# end, so 2.5 kg was stored as 2, 12.75 m as 13 and 0.4 kg was dropped - for
# grocery, restaurants, textiles, manufacturing and hourly services alike.

def test_fractional_quantities_are_imported_exactly(conn, seeded_tenant):
    tenant_id, user_id, job_id = seeded_tenant
    rows = [
        _template_row(product_name="Tomatoes (kg)", quantity="2.5", unit_price="1.20"),
        _template_row(product_name="Consulting (hour)", quantity="1.5", unit_price="40"),
        _template_row(product_name="Cotton fabric (m)", quantity="12.75", unit_price="3.10"),
        _template_row(product_name="Saffron (g)", quantity="0.4", unit_price="12.3456"),
    ]
    _, result = _run(conn, tenant_id, job_id, user_id, rows)
    conn.commit()

    assert result.rows_promoted == 4
    items = {(q, p, t) for _, q, p, t, *_ in _invoice_items_for_tenant(conn, tenant_id)}
    assert items == {
        (Decimal("2.5000"), Decimal("1.2000"), Decimal("3.0000")),
        (Decimal("1.5000"), Decimal("40.0000"), Decimal("60.0000")),
        (Decimal("12.7500"), Decimal("3.1000"), Decimal("39.5250")),
        # Owner-approved effective paid price: 4.9382 / 0.4 = 12.3455.
        # The source 12.3456 remains in staging/product evidence; paid total is unchanged.
        (Decimal("0.4000"), Decimal("12.3455"), Decimal("4.9382")),
    }


def test_dedupe_identity_uses_only_values_from_the_file(conn, seeded_tenant):
    """Derived values (the line total) must not be part of the identity: a
    change in how a total is derived would otherwise make a re-imported file
    look new and duplicate it."""
    tenant_id, user_id, job_id = seeded_tenant
    row = _template_row(product_name="Widget", quantity="3", unit_price="2.00")
    first = promotion._import_invoice_number("widget|2026-08-30|3|2.00|||JOD||", 1)
    _run(conn, tenant_id, job_id, user_id, [row])
    conn.commit()
    numbers = [invoice_number for *_, invoice_number in _invoice_items_for_tenant(conn, tenant_id)]
    assert numbers == [first]


def test_dot_decimal_prices_are_not_inflated_for_a_comma_decimal_country(conn, seeded_tenant):
    """Found live: a Moroccan tenant (comma-decimal locale) importing a
    dot-decimal POS export had 1.20 stored as 120.00 and 3.10 as 310.00."""
    tenant_id, user_id, job_id = seeded_tenant
    with conn.cursor() as cursor:
        cursor.execute("UPDATE companies SET country_code = 'MA', primary_currency = 'MAD' WHERE tenant_id = %s;", (tenant_id,))
    conn.commit()
    rows = [
        _template_row(product_name="Mint tea", quantity="2", unit_price="1.20", currency="MAD"),
        _template_row(product_name="Argan oil", quantity="1", unit_price="1.250", currency="MAD"),  # 3 digits: locale decides
        _template_row(product_name="Couscous", quantity="1", unit_price="12,50", currency="MAD"),
    ]
    _, result = _run(conn, tenant_id, job_id, user_id, rows)
    conn.commit()

    assert result.rows_promoted == 3
    prices = sorted(p for _, _, p, *_ in _invoice_items_for_tenant(conn, tenant_id))
    assert prices == [Decimal("1.2000"), Decimal("12.5000"), Decimal("1250.0000")]


def test_rows_named_in_any_of_a_products_languages_match_the_existing_product(conn, seeded_tenant):
    """A POS exporting Arabic item names must not duplicate a catalog product
    that already has that Arabic name (only 'en' used to be matched)."""
    tenant_id, user_id, job_id = seeded_tenant
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (tenant_id, product_name, current_price, currency) VALUES (%s, %s::jsonb, 4.2, 'JOD') RETURNING product_id;",
            (tenant_id, '{"en": "Fresh Labneh (per kg)", "ar": "لبنة طازجة (كيلو)"}'),
        )
        product_id = str(cursor.fetchone()[0])
    conn.commit()
    _, result = _run(conn, tenant_id, job_id, user_id, [
        _template_row(product_name="لبنة طازجة (كيلو)", quantity="1.5", unit_price="4.2"),
        _template_row(product_name="زعتر بلدي", quantity="2", unit_price="3.25"),
    ])
    conn.commit()
    assert result.products_created == 1
    items = _invoice_items_for_tenant(conn, tenant_id)
    assert product_id in {str(item[0]) for item in items}
    with conn.cursor() as cursor:
        cursor.execute("SELECT product_name FROM products WHERE tenant_id = %s AND product_id <> %s;", (tenant_id, product_id))
        assert cursor.fetchone()[0] == {"ar": "زعتر بلدي"}  # Arabic name stored as Arabic


def test_paid_amount_rounded_up_to_the_currency_unit_is_trusted():
    """237.35 x 0.965 JOD = 229.04275, printed as 229.043 (3-decimal dinar):
    above the exact gross by under half a fils - still the amount paid."""
    fields = {"amount_raw": "229.043"}
    assert promotion._line_total(fields, Decimal("237.35"), Decimal("0.965"), "JOD") == Decimal("229.0430")
    # ...but not a whole unit above it (a tax-inclusive or whole-order figure)
    assert promotion._line_total({"amount_raw": "229.044"}, Decimal("237.35"), Decimal("0.965"), "JOD") == Decimal("229.0428")
    assert promotion._line_total({"amount_raw": "1500"}, Decimal("1"), Decimal("1499.6"), "XOF") == Decimal("1500.0000")


def _run_with_barcode(conn, tenant_id, job_id, user_id, rows):
    summary = ingestion_pipeline.process_records(
        tenant_id=tenant_id, job_id=job_id, source_name="f.csv", headers=_TEMPLATE_HEADERS + ["barcode"], rows=rows, conn=conn,
    )
    return summary, promotion.promote_ingested_rows(conn, tenant_id, job_id, summary, user_id=user_id)


def _barcode_of(conn, name, tenant_id):
    with conn.cursor() as cursor:
        cursor.execute("SELECT metadata->>'barcode' FROM products WHERE tenant_id = %s AND product_name->>'en' = %s AND deleted_at IS NULL;", (tenant_id, name))
        rows = cursor.fetchall()
    return [r[0] for r in rows]


def test_barcode_column_sets_the_barcode_on_a_new_product_and_repairs_excel_formatting(conn, seeded_tenant):
    tenant_id, user_id, job_id = seeded_tenant
    _, promo = _run_with_barcode(conn, tenant_id, job_id, user_id, [_template_row(product_name="Nutella 400g", barcode="3.017620422003E+12")])
    conn.commit()
    assert promo.rows_promoted == 1 and promo.barcodes_applied == 1
    assert _barcode_of(conn, "Nutella 400g", tenant_id) == ["3017620422003"]


def test_an_invalid_barcode_never_blocks_the_sale_and_a_curated_barcode_is_never_overwritten(conn, seeded_tenant):
    tenant_id, user_id, job_id = seeded_tenant
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (tenant_id, product_name, current_price, currency, source, metadata) "
            "VALUES (%s, '{\"en\": \"Curated\"}'::jsonb, 5, 'JOD', 'MANUAL', '{\"barcode\": \"96385074\"}'::jsonb);",
            (tenant_id,),
        )
    conn.commit()
    _, promo = _run_with_barcode(conn, tenant_id, job_id, user_id, [
        _template_row(product_name="Bad Code", barcode="3017620422004"),        # wrong check digit
        _template_row(product_name="Curated", barcode="3017620422003"),         # already has 96385074
    ])
    conn.commit()
    assert promo.rows_promoted == 2 and promo.barcodes_applied == 0
    assert _barcode_of(conn, "Bad Code", tenant_id) == [None]
    assert _barcode_of(conn, "Curated", tenant_id) == ["96385074"]


def test_a_product_named_differently_in_the_file_is_matched_by_its_barcode(conn, seeded_tenant):
    tenant_id, user_id, job_id = seeded_tenant
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (tenant_id, product_name, current_price, currency, source, metadata) "
            "VALUES (%s, '{\"en\": \"Nutella Hazelnut Spread 400g\"}'::jsonb, 5, 'JOD', 'MANUAL', '{\"barcode\": \"3017620422003\"}'::jsonb);",
            (tenant_id,),
        )
    conn.commit()
    _, promo = _run_with_barcode(conn, tenant_id, job_id, user_id, [_template_row(product_name="NUTELLA JAR 400", barcode="3017620422003")])
    conn.commit()
    assert promo.rows_promoted == 1 and promo.products_created == 0 and promo.products_matched_by_barcode == 1
    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM products WHERE tenant_id = %s AND deleted_at IS NULL;", (tenant_id,))
        assert cursor.fetchone()[0] == 1

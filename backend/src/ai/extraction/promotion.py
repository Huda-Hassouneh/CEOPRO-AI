"""
KEEL - Staging -> Canonical Promotion.

Moves eligible import_staging_rows rows into their real destination
tables (products/transactions) - import_staging_rows is a temporary
landing zone, not the final destination. No schema change needed:
chk_committed_table_guard already allows committed_table='transactions'
as of migrations/20260830020000_add_field_level_ingestion_tracking.sql
(written earlier this session specifically to unblock this feature).

Promotion runs synchronously inside the same request/transaction as
ingestion_pipeline.process_records() (see main.py's /extraction/upload),
consuming IngestionSummary.row_outcomes directly while typed_fields are
still hot in memory - avoids re-parsing raw_payload_json a second time
with a second implementation that could drift from row_parsing.py.

Bulk, not per-row: a naive one-INSERT-per-row promotion of a 50k-row
file would reproduce the exact 8.5-hour SAVEPOINT-per-row scaling cliff
already root-caused and fixed once for staging inserts (see SCALING.md).
Eligible rows are batched (_PROMOTION_BATCH_SIZE) and written with
psycopg2.extras.execute_values() - one round trip per batch, not one
per row. Each batch (and the upfront product-creation pass) runs inside
its own SAVEPOINT; on failure, only that unit rolls back and retries
row-by-row (each row its own SAVEPOINT) to isolate exactly which row is
bad without losing the rest of the batch or the file - fields are
already type/range-validated by row_parsing.py before promotion ever
sees them, so a batch failure should be rare, but a rare failure must
never silently drop otherwise-good rows.
"""
import hashlib
import json
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Callable, Dict, List, Optional, Tuple, TypeVar

import psycopg2.errors
from psycopg2.extras import execute_values

from src.ai.core import usage
from src.ai.core.money import minor_units
from src.ai.core.quantities import as_quantity
from src.ai.extraction.ingestion_pipeline import IngestionSummary
from src.ai.extraction.template_contract import REQUIRED_TEMPLATE_FIELDS

_PROMOTION_BATCH_SIZE = 1000
_BATCH_SAVEPOINT = "promotion_batch_write"
_ROW_SAVEPOINT = "promotion_row_write"
_PRODUCT_SAVEPOINT = "promotion_product_write"

T = TypeVar("T")


@dataclass
class PromotionSummary:
    rows_promoted: int = 0
    rows_skipped_incomplete: int = 0
    rows_failed: int = 0
    # Rows this tenant had already imported (same content, see
    # _import_invoice_number) - skipped, not written a second time.
    rows_duplicate: int = 0
    products_created: int = 0
    # Rows whose product would have exceeded the plan's product limit.
    rows_over_product_limit: int = 0
    errors: List[Dict] = field(default_factory=list)


@dataclass
class _EligibleRow:
    row_index: int
    staging_row_id: int
    product_name_normalized: str
    product_name_raw: str
    quantity: Decimal  # exact, may be fractional (2.5 kg, 1.5 h)
    unit_price: Decimal
    currency: str
    transaction_date: str
    # What the customer actually paid for this line (see _line_total()).
    # Defaults to quantity x unit_price for callers that build rows directly.
    line_total: Optional[Decimal] = None
    # Deterministic per-content invoice number (see _import_invoice_number);
    # None falls back to the legacy per-job number.
    invoice_number: Optional[str] = None

    def __post_init__(self):
        self.quantity = Decimal(self.quantity)
        if self.line_total is None:
            self.line_total = _round4(self.quantity * self.unit_price)
        # Otherwise line_total stays exactly what the customer paid. A paid
        # total like 15.53 for 3 units has no exact 4-dp unit price; the
        # stored effective_unit_price reproduces it to within 0.00005 per
        # unit, which is what chk_total_price_consistent allows (migration
        # 20261006020000). It used to be snapped instead, so recorded
        # revenue drifted from the money actually received.

    @property
    def effective_unit_price(self) -> Decimal:
        """Unit price actually paid (after any discount) - stored as unit_price
        so quantity x unit_price == total_price in every table."""
        if not self.quantity or self.line_total == _round4(self.quantity * self.unit_price):
            return self.unit_price  # no discount: the list price, exactly
        return _round4(self.line_total / self.quantity)


_CENT4 = Decimal("0.0001")


def _round4(value: Decimal) -> Decimal:
    """Round to 4 dp the way Postgres ROUND(numeric, 4) does (half away from
    zero) - the CHECK constraint recomputes this product in SQL."""
    return value.quantize(_CENT4, rounding=ROUND_HALF_UP)


def _line_total(fields: dict, quantity: Decimal, unit_price: Decimal, currency: Optional[str] = None) -> Decimal:
    """The amount the customer actually paid for one sales line.

    Real bug found in first-customer acceptance testing: every imported row
    was recorded at quantity x list price, ignoring the template's own
    discount_pct and amount_raw columns - a 10%-off line (the template's own
    example: 3 x 24.50 at 10% off, amount_raw 66.15) was recorded as 73.50,
    so Dashboard revenue, reports and the RAG sales summary overstated what
    the business actually earned (1.05% on a realistic 120-day dataset with
    8% discounted lines).

    Precedence: amount_raw (the paid line total, unambiguous) when it's a
    plausible discount of the list total; otherwise discount_pct (a
    percentage, 0-100); otherwise the list total. amount_raw above the list
    total (e.g. a tax-inclusive or whole-order figure) or non-positive is
    not trusted as a line discount and falls through.
    """
    gross = _round4(quantity * unit_price)
    # A real receipt rounds to the currency's smallest unit, so an undiscounted
    # 237.35 kg x 0.965 JOD = 229.04275 prints as 229.043 - above the exact
    # gross by less than half a fils. Allow that rounding (found reconciling a
    # B2B ERP export: those lines fell back to the unrounded gross).
    half_minor_unit = Decimal(5).scaleb(-(minor_units(currency) + 1))
    raw_amount = fields.get("amount_raw")
    if raw_amount not in (None, ""):
        try:
            paid = Decimal(str(raw_amount)).quantize(_CENT4)
        except (InvalidOperation, ValueError):
            paid = None
        if paid is not None and Decimal("0") < paid <= gross + half_minor_unit:
            return paid
    raw_discount = fields.get("discount_pct")
    if raw_discount not in (None, ""):
        try:
            pct = Decimal(str(raw_discount))
        except (InvalidOperation, ValueError):
            pct = None
        if pct is not None and Decimal("0") < pct <= Decimal("100"):
            return (gross * (Decimal("100") - pct) / Decimal("100")).quantize(_CENT4)
    return gross


def _import_invoice_number(material: str, occurrence: int) -> str:
    """A content-derived invoice number for an imported sales line.

    Real bug found in first-customer acceptance testing: uploading the same
    sales file twice imported every row twice (1,597 -> 3,194 invoices,
    doubling Dashboard revenue) - imported invoices were numbered
    IMPORT-<job>-<row>, unique per upload. Re-uploading an export, or an
    overlapping period, is routine for a real customer.

    The number is now derived from the row's own content (product, date,
    quantity, prices, paid total, currency, and the source invoice/order id
    when the file has one) plus its occurrence count within the file - two
    genuinely identical sales on the same day in one file stay two rows -
    so re-importing the same rows maps to the same numbers, and invoices'
    existing UNIQUE (tenant_id, invoice_number) rejects them.
    """
    digest = hashlib.sha256(f"{material}#{occurrence}".encode("utf-8")).hexdigest()[:32]
    return f"IMP-{digest}"


def _run_in_savepoint(conn, name: str, fn: Callable[[], T]) -> T:
    """Runs fn() inside a named SAVEPOINT - releases on success, rolls back
    to it (and re-raises) on failure, so the caller's outer transaction
    survives either way. See ingestion_pipeline._execute_in_savepoint()
    for the same pattern applied to a single statement; this version wraps
    an arbitrary callable so a batch (multiple statements) or a row (an
    INSERT + its staging UPDATE) can be made atomic as one unit."""
    with conn.cursor() as cursor:
        cursor.execute(f"SAVEPOINT {name};")
    try:
        result = fn()
    except Exception:
        with conn.cursor() as cursor:
            cursor.execute(f"ROLLBACK TO SAVEPOINT {name};")
        raise
    else:
        with conn.cursor() as cursor:
            cursor.execute(f"RELEASE SAVEPOINT {name};")
        return result


_REQUIRED_MINUS_CURRENCY = REQUIRED_TEMPLATE_FIELDS - {"currency"}


def _extract_eligible_rows(
    summary: IngestionSummary, default_currency: Optional[str] = None,
) -> Tuple[List[_EligibleRow], int]:
    """A row is promotable iff every REQUIRED_TEMPLATE_FIELDS key survived
    into typed_fields - correctly covers both VALID rows and PARTIAL rows
    whose dropped field(s) were optional (a bad `email` shouldn't block
    promotion; a bad `quantity` already isn't in typed_fields by the time
    this runs, since _process_mapped_row() already popped it).

    `currency` is the one required field allowed to fall back to
    `default_currency` (the tenant's companies.primary_currency) instead of
    being present in the row itself - real POS exports routinely have no
    per-row currency column at all (confirmed against mocks/
    Electronics_For_Test.xlsx: Sale_ID/Date_Time/Product_ID/Product_Name/
    Quantity/Unit_Price/Total_Price/Shift, no currency column anywhere)
    because the business only ever transacts in one currency - without this,
    every row from a file shaped like that would be skipped as "incomplete"
    even though nothing is actually missing or ambiguous. A row's own
    explicit currency column, when present, always wins over the default."""
    eligible: List[_EligibleRow] = []
    skipped = 0
    occurrences: Dict[str, int] = {}
    for outcome in summary.row_outcomes:
        if outcome.staging_row_id is None or outcome.parse_result is None:
            continue
        fields = outcome.parse_result.typed_fields
        if not _REQUIRED_MINUS_CURRENCY.issubset(fields.keys()):
            skipped += 1
            continue
        currency = fields.get("currency") or default_currency
        if not currency:
            skipped += 1
            continue
        try:
            quantity = _round4(Decimal(fields["quantity"]))
            unit_price = Decimal(fields["unit_price"])
        except (ValueError, InvalidOperation):
            skipped += 1
            continue
        if quantity <= 0:
            skipped += 1
            continue
        name_raw = fields["product_name"].strip()
        if not name_raw:
            skipped += 1
            continue
        line_total = _line_total(fields, quantity, unit_price, currency)
        # Dedupe identity is built only from what the FILE says (normalised),
        # never from values this module derives (like line_total): a change in
        # how a total is derived must not make a re-imported file look new.
        material = "|".join(str(part) for part in (
            name_raw.casefold(), fields["transaction_date"], as_quantity(quantity), unit_price,
            (fields.get("amount_raw") or "").strip(), (fields.get("discount_pct") or "").strip(), currency,
            (fields.get("invoice_id") or "").strip(), (fields.get("order_id") or "").strip(),
        ))
        occurrences[material] = occurrences.get(material, 0) + 1
        eligible.append(
            _EligibleRow(
                row_index=outcome.row_index,
                staging_row_id=outcome.staging_row_id,
                product_name_normalized=name_raw.casefold(),
                product_name_raw=name_raw,
                quantity=quantity,
                unit_price=unit_price,
                currency=currency,
                transaction_date=fields["transaction_date"],
                line_total=line_total,
                invoice_number=_import_invoice_number(material, occurrences[material]),
            )
        )
    return eligible, skipped


def _load_existing_products(conn, tenant_id: str) -> Dict[str, str]:
    """Every name a product has, in every language. Found in acceptance
    testing: only the English name was matched, so a catalog product
    {"en": "Fresh Labneh", "ar": "لبنة طازجة"} sold through a POS that
    exports Arabic item names got a duplicate product on every import."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT product_id, product_name FROM products "
            "WHERE tenant_id = %s AND deleted_at IS NULL;",
            (tenant_id,),
        )
        rows = cursor.fetchall()
    known: Dict[str, str] = {}
    for product_id, names in rows:
        values = names.values() if isinstance(names, dict) else [names]
        for name in values:
            if isinstance(name, str) and name.strip():
                known.setdefault(name.strip().casefold(), str(product_id))
    return known


_ARABIC_SCRIPT = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")


def _name_json(raw_name: str) -> str:
    """An imported name in Arabic script is an Arabic name, not English -
    every display path falls back en -> ar, so this renders identically
    and leaves "en" free for a translation the owner adds later."""
    return json.dumps({"ar" if _ARABIC_SCRIPT.search(raw_name) else "en": raw_name}, ensure_ascii=False)


def _bulk_insert_products(
    conn, tenant_id: str, user_id: Optional[str], job_id: str,
    to_create: Dict[str, Tuple[str, str, Decimal]],
) -> Dict[str, str]:
    metadata = json.dumps({"promoted_from_job_id": job_id})
    names = list(to_create.keys())
    values = [
        (tenant_id, _name_json(raw_name), price, currency, "IMPORTED", metadata, user_id, user_id)
        for raw_name, currency, price in (to_create[n] for n in names)
    ]
    with conn.cursor() as cursor:
        results = execute_values(
            cursor,
            """
            INSERT INTO products
                (tenant_id, product_name, current_price, currency, source, metadata,
                 created_by_user_id, updated_by_user_id)
            VALUES %s
            RETURNING product_id;
            """,
            values,
            template="(%s, %s::jsonb, %s, %s, %s, %s::jsonb, %s, %s)",
            fetch=True,
        )
    return {name: str(result[0]) for name, result in zip(names, results)}


def _insert_one_product(
    conn, tenant_id: str, user_id: Optional[str], job_id: str, raw_name: str, currency: str, price: Decimal,
) -> str:
    metadata = json.dumps({"promoted_from_job_id": job_id})
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO products
                (tenant_id, product_name, current_price, currency, source, metadata,
                 created_by_user_id, updated_by_user_id)
            VALUES (%s, %s::jsonb, %s, %s, 'IMPORTED', %s::jsonb, %s, %s)
            RETURNING product_id;
            """,
            (tenant_id, _name_json(raw_name), price, currency, metadata, user_id, user_id),
        )
        return str(cursor.fetchone()[0])


def _create_missing_products(
    conn, tenant_id: str, user_id: Optional[str], job_id: str,
    rows: List[_EligibleRow], known: Dict[str, str],
) -> int:
    """Bulk-creates one products row per distinct not-yet-known normalized
    name across `rows`, updating `known` in place. Never touches an
    existing product's current_price/currency - a historical transaction
    import must not silently overwrite a curated catalog price."""
    to_create: Dict[str, Tuple[str, str, Decimal]] = {}
    for row in rows:
        if row.product_name_normalized not in known and row.product_name_normalized not in to_create:
            to_create[row.product_name_normalized] = (row.product_name_raw, row.currency, row.unit_price)
    # The plan's product limit applies to imports too: only as many new
    # products as still fit are created (in file order); rows for the rest
    # are reported as over the limit by the caller.
    room = usage.capacity_left(conn, tenant_id, usage.TRACKED_PRODUCTS)
    if room is not None and len(to_create) > room:
        to_create = dict(list(to_create.items())[:int(room)])
    if not to_create:
        return 0

    try:
        created = _run_in_savepoint(
            conn, _PRODUCT_SAVEPOINT,
            lambda: _bulk_insert_products(conn, tenant_id, user_id, job_id, to_create),
        )
        known.update(created)
        return len(created)
    except Exception:
        pass  # fall through to the isolated, row-by-row retry below

    created_count = 0
    for normalized_name, (raw_name, currency, price) in to_create.items():
        try:
            product_id = _run_in_savepoint(
                conn, _PRODUCT_SAVEPOINT,
                lambda: _insert_one_product(conn, tenant_id, user_id, job_id, raw_name, currency, price),
            )
        except Exception:
            continue  # left unresolved; rows needing this product are counted as failures below
        known[normalized_name] = product_id
        created_count += 1
    return created_count


def _insert_invoices_mirror_batch(
    conn, tenant_id: str, job_id: str, user_id: Optional[str], batch: List[_EligibleRow], known: Dict[str, str],
) -> None:
    """
    Mirrors each imported transaction into invoices/invoice_items - the
    table pair the dashboard (dashboard/metrics.py, financial_summary.py,
    forecast_detail.py, reports.py) and the RAG sales-history summary
    (rag/structured_summaries.py::generate_sales_history_summary) actually
    read, same as a manual Quick Sale already does (sales/quick_sale.py).

    Real bug this closes, found live in UAT: a customer who bulk-imports
    sales history (this pipeline's own canonical use case) saw it reach
    Demand Prediction (forecasting/data_access.py reads `transactions`,
    written by _insert_transactions_batch above) but NOT their own
    Dashboard or chatbot - both kept reading invoices/invoice_items,
    which only ever got rows from a manual Quick Sale. `transactions` was
    added later (see migrations/20260830000000_add_transactions_and_
    model_versions.sql) for forecasting's per-line-item needs without the
    dashboard/RAG side being updated to match - chk_committed_table_guard
    already allowed 'invoices'/'invoice_items' as commit targets before
    'transactions' even existed, confirming this was the original,
    intended destination. One invoice per imported row (not grouped by
    the file's own optional invoice_id column) deliberately mirrors
    transactions' own one-row-per-sale granularity exactly, so neither
    table can end up with a different total than the other.

    Same batch/SAVEPOINT as the transactions insert (see
    _insert_transactions_batch's caller) - either both tables gain this
    batch's rows or neither does, so the two can never drift out of sync
    from a partial failure.
    """
    invoice_values = []
    for row in batch:
        invoice_number = row.invoice_number or f"IMPORT-{job_id}-{row.row_index}"
        invoice_values.append((
            tenant_id, invoice_number, row.transaction_date, row.line_total, row.line_total,
            row.currency, user_id,
        ))
    with conn.cursor() as cursor:
        invoice_ids = execute_values(
            cursor,
            """
            INSERT INTO invoices
                (tenant_id, invoice_number, issue_date, subtotal, total_amount, currency,
                 payment_status, created_by_user_id)
            VALUES %s
            RETURNING invoice_id;
            """,
            invoice_values,
            template="(%s, %s, %s::timestamptz, %s, %s, %s, 'PAID', %s)",
            fetch=True,
        )

    item_values = []
    for row, (invoice_id,) in zip(batch, invoice_ids):
        item_values.append((
            tenant_id, str(invoice_id), known[row.product_name_normalized], row.quantity,
            row.effective_unit_price, row.line_total,
        ))
    with conn.cursor() as cursor:
        execute_values(
            cursor,
            """
            INSERT INTO invoice_items (tenant_id, invoice_id, product_id, quantity, unit_price, total_price)
            VALUES %s;
            """,
            item_values,
            template="(%s, %s, %s, %s, %s, %s)",
        )


def _insert_invoice_mirror_row(
    conn, tenant_id: str, job_id: str, user_id: Optional[str], row: _EligibleRow, known: Dict[str, str],
) -> None:
    """Row-by-row fallback counterpart to _insert_invoices_mirror_batch -
    see that function's docstring for why this mirror exists."""
    total_price = row.line_total
    invoice_number = row.invoice_number or f"IMPORT-{job_id}-{row.row_index}"
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO invoices
                (tenant_id, invoice_number, issue_date, subtotal, total_amount, currency,
                 payment_status, created_by_user_id)
            VALUES (%s, %s, %s::timestamptz, %s, %s, %s, 'PAID', %s)
            RETURNING invoice_id;
            """,
            (tenant_id, invoice_number, row.transaction_date, total_price, total_price, row.currency, user_id),
        )
        invoice_id = str(cursor.fetchone()[0])
        cursor.execute(
            """
            INSERT INTO invoice_items (tenant_id, invoice_id, product_id, quantity, unit_price, total_price)
            VALUES (%s, %s, %s, %s, %s, %s);
            """,
            (tenant_id, invoice_id, known[row.product_name_normalized], row.quantity, row.effective_unit_price, total_price),
        )


def _insert_transactions_batch(
    conn, tenant_id: str, job_id: str, user_id: Optional[str], batch: List[_EligibleRow], known: Dict[str, str],
) -> List[Tuple[int, str]]:
    values = []
    for row in batch:
        values.append((
            tenant_id, known[row.product_name_normalized], row.quantity, row.effective_unit_price,
            row.line_total, row.currency, row.transaction_date,
        ))
    with conn.cursor() as cursor:
        results = execute_values(
            cursor,
            """
            INSERT INTO transactions
                (tenant_id, product_id, quantity_sold, unit_price, total_price,
                 original_currency, sale_source, transaction_date)
            VALUES %s
            RETURNING transaction_id;
            """,
            values,
            template="(%s, %s, %s, %s, %s, %s, 'POS', %s::timestamptz)",
            fetch=True,
        )
    _insert_invoices_mirror_batch(conn, tenant_id, job_id, user_id, batch, known)
    return [(row.staging_row_id, str(result[0])) for row, result in zip(batch, results)]


def _update_staging_rows_batch(conn, pairs: List[Tuple[int, str]]) -> None:
    with conn.cursor() as cursor:
        execute_values(
            cursor,
            """
            UPDATE import_staging_rows AS s
            SET committed_table = 'transactions', committed_record_id = v.transaction_id::uuid,
                validation_status = 'COMMITTED'
            FROM (VALUES %s) AS v(staging_row_id, transaction_id)
            WHERE s.staging_row_id = v.staging_row_id;
            """,
            pairs,
            template="(%s, %s)",
        )


def _insert_transaction_row(
    conn, tenant_id: str, job_id: str, user_id: Optional[str], row: _EligibleRow, known: Dict[str, str],
) -> str:
    total_price = row.line_total
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO transactions
                (tenant_id, product_id, quantity_sold, unit_price, total_price,
                 original_currency, sale_source, transaction_date)
            VALUES (%s, %s, %s, %s, %s, %s, 'POS', %s::timestamptz)
            RETURNING transaction_id;
            """,
            (tenant_id, known[row.product_name_normalized], row.quantity, row.effective_unit_price,
             total_price, row.currency, row.transaction_date),
        )
        transaction_id = str(cursor.fetchone()[0])
    _insert_invoice_mirror_row(conn, tenant_id, job_id, user_id, row, known)
    return transaction_id


def _update_staging_row(conn, staging_row_id: int, transaction_id: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE import_staging_rows
            SET committed_table = 'transactions', committed_record_id = %s::uuid, validation_status = 'COMMITTED'
            WHERE staging_row_id = %s;
            """,
            (transaction_id, staging_row_id),
        )


def _promote_batch_row_by_row(
    conn, tenant_id: str, job_id: str, user_id: Optional[str], batch: List[_EligibleRow],
    known: Dict[str, str], result: PromotionSummary,
) -> None:
    for row in batch:
        def _do(row=row):
            transaction_id = _insert_transaction_row(conn, tenant_id, job_id, user_id, row, known)
            _update_staging_row(conn, row.staging_row_id, transaction_id)

        try:
            _run_in_savepoint(conn, _ROW_SAVEPOINT, _do)
        except psycopg2.errors.UniqueViolation:
            # Same content already imported (e.g. a concurrent upload of the
            # same file won the race) - a duplicate, not a failure.
            result.rows_duplicate += 1
        except Exception as e:  # noqa: BLE001 - one bad row must not sink the rest of the fallback pass
            result.rows_failed += 1
            result.errors.append({"row_index": row.row_index, "error": str(e)})
        else:
            result.rows_promoted += 1


def _existing_invoice_numbers(conn, tenant_id: str, numbers: List[Optional[str]]) -> set:
    numbers = [n for n in numbers if n]
    if not numbers:
        return set()
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT invoice_number FROM invoices WHERE tenant_id = %s AND invoice_number = ANY(%s);",
            (tenant_id, numbers),
        )
        return {row[0] for row in cursor.fetchall()}


def promote_ingested_rows(
    conn, tenant_id: str, job_id: str, summary: IngestionSummary, user_id: Optional[str] = None,
    default_currency: Optional[str] = None,
) -> PromotionSummary:
    """
    Promotes this job's eligible staging rows into products/transactions.
    Call right after ingestion_pipeline.process_records() returns, on the
    same open `conn` - see main.py's /extraction/upload for the wiring.
    Safe to call with conn=None (no-op, matching process_records()'s own
    dry-run convention) - returns an empty PromotionSummary.

    default_currency: falls back to this (typically the tenant's
    companies.primary_currency) for a row whose file had no currency
    column at all - see _extract_eligible_rows()'s own docstring.
    """
    result = PromotionSummary()
    if conn is None:
        return result

    eligible, skipped = _extract_eligible_rows(summary, default_currency=default_currency)
    result.rows_skipped_incomplete = skipped
    if not eligible:
        return result

    known = _load_existing_products(conn, tenant_id)
    known_before = set(known)
    result.products_created = _create_missing_products(conn, tenant_id, user_id, job_id, eligible, known)
    room_left = usage.capacity_left(conn, tenant_id, usage.TRACKED_PRODUCTS)

    # A row whose product still isn't in `known` (product creation failed
    # for that name even after the row-by-row retry) can't be promoted -
    # counted as a genuine failure, not silently dropped.
    promotable = []
    for row in eligible:
        if row.product_name_normalized in known:
            promotable.append(row)
        elif room_left == 0 and row.product_name_normalized not in known_before:
            result.rows_failed += 1
            result.rows_over_product_limit += 1
            result.errors.append({"row_index": row.row_index, "error": "plan product limit reached"})
        else:
            result.rows_failed += 1
            result.errors.append({"row_index": row.row_index, "error": "product resolution failed"})

    already_imported = _existing_invoice_numbers(conn, tenant_id, [row.invoice_number for row in promotable])
    if already_imported:
        result.rows_duplicate += sum(1 for row in promotable if row.invoice_number in already_imported)
        promotable = [row for row in promotable if row.invoice_number not in already_imported]

    for start in range(0, len(promotable), _PROMOTION_BATCH_SIZE):
        batch = promotable[start : start + _PROMOTION_BATCH_SIZE]

        def _do(batch=batch):
            pairs = _insert_transactions_batch(conn, tenant_id, job_id, user_id, batch, known)
            _update_staging_rows_batch(conn, pairs)
            return pairs

        try:
            pairs = _run_in_savepoint(conn, _BATCH_SAVEPOINT, _do)
        except Exception:
            _promote_batch_row_by_row(conn, tenant_id, job_id, user_id, batch, known, result)
        else:
            result.rows_promoted += len(pairs)

    return result

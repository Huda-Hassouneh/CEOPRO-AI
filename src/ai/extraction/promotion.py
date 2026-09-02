"""
CEOPRO AI - Staging -> Canonical Promotion.

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
import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Callable, Dict, List, Optional, Tuple, TypeVar

from psycopg2.extras import execute_values

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
    products_created: int = 0
    errors: List[Dict] = field(default_factory=list)


@dataclass
class _EligibleRow:
    row_index: int
    staging_row_id: int
    product_name_normalized: str
    product_name_raw: str
    quantity: int
    unit_price: Decimal
    currency: str
    transaction_date: str


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
            quantity = int(fields["quantity"])
            unit_price = Decimal(fields["unit_price"])
        except (ValueError, InvalidOperation):
            skipped += 1
            continue
        name_raw = fields["product_name"].strip()
        if not name_raw:
            skipped += 1
            continue
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
            )
        )
    return eligible, skipped


def _load_existing_products(conn, tenant_id: str) -> Dict[str, str]:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT product_id, product_name->>'en' FROM products "
            "WHERE tenant_id = %s AND deleted_at IS NULL;",
            (tenant_id,),
        )
        rows = cursor.fetchall()
    return {name.strip().casefold(): str(product_id) for product_id, name in rows if name}


def _bulk_insert_products(
    conn, tenant_id: str, user_id: Optional[str], job_id: str,
    to_create: Dict[str, Tuple[str, str, Decimal]],
) -> Dict[str, str]:
    metadata = json.dumps({"promoted_from_job_id": job_id})
    names = list(to_create.keys())
    values = [
        (tenant_id, json.dumps({"en": raw_name}), price, currency, "IMPORTED", metadata, user_id, user_id)
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
            (tenant_id, json.dumps({"en": raw_name}), price, currency, metadata, user_id, user_id),
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


def _insert_transactions_batch(
    conn, tenant_id: str, batch: List[_EligibleRow], known: Dict[str, str],
) -> List[Tuple[int, str]]:
    values = []
    for row in batch:
        total_price = (row.quantity * row.unit_price).quantize(Decimal("0.0001"))
        values.append((
            tenant_id, known[row.product_name_normalized], row.quantity, row.unit_price,
            total_price, row.currency, row.transaction_date,
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


def _insert_transaction_row(conn, tenant_id: str, row: _EligibleRow, known: Dict[str, str]) -> str:
    total_price = (row.quantity * row.unit_price).quantize(Decimal("0.0001"))
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO transactions
                (tenant_id, product_id, quantity_sold, unit_price, total_price,
                 original_currency, sale_source, transaction_date)
            VALUES (%s, %s, %s, %s, %s, %s, 'POS', %s::timestamptz)
            RETURNING transaction_id;
            """,
            (tenant_id, known[row.product_name_normalized], row.quantity, row.unit_price,
             total_price, row.currency, row.transaction_date),
        )
        return str(cursor.fetchone()[0])


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
    conn, tenant_id: str, batch: List[_EligibleRow], known: Dict[str, str], result: PromotionSummary,
) -> None:
    for row in batch:
        def _do(row=row):
            transaction_id = _insert_transaction_row(conn, tenant_id, row, known)
            _update_staging_row(conn, row.staging_row_id, transaction_id)

        try:
            _run_in_savepoint(conn, _ROW_SAVEPOINT, _do)
        except Exception as e:  # noqa: BLE001 - one bad row must not sink the rest of the fallback pass
            result.rows_failed += 1
            result.errors.append({"row_index": row.row_index, "error": str(e)})
        else:
            result.rows_promoted += 1


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
    result.products_created = _create_missing_products(conn, tenant_id, user_id, job_id, eligible, known)

    # A row whose product still isn't in `known` (product creation failed
    # for that name even after the row-by-row retry) can't be promoted -
    # counted as a genuine failure, not silently dropped.
    promotable = []
    for row in eligible:
        if row.product_name_normalized in known:
            promotable.append(row)
        else:
            result.rows_failed += 1
            result.errors.append({"row_index": row.row_index, "error": "product resolution failed"})

    for start in range(0, len(promotable), _PROMOTION_BATCH_SIZE):
        batch = promotable[start : start + _PROMOTION_BATCH_SIZE]

        def _do(batch=batch):
            pairs = _insert_transactions_batch(conn, tenant_id, batch, known)
            _update_staging_rows_batch(conn, pairs)
            return pairs

        try:
            pairs = _run_in_savepoint(conn, _BATCH_SAVEPOINT, _do)
        except Exception:
            _promote_batch_row_by_row(conn, tenant_id, batch, known, result)
        else:
            result.rows_promoted += len(pairs)

    return result

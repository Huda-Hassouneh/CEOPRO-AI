"""
CEOPRO AI - Ingestion Pipeline Orchestrator.

Implements the full target architecture end-to-end for one uploaded file
or one batch of records from a live integration, at zero infrastructure
cost:

    Input (file OR caller-supplied records) -> Tier Resolution ->
    Structured Parsing / Fallback Extraction -> Field-Level Validation ->
    Normalization -> Catalog Matching -> Canonical Extraction Output ->
    import_staging_rows (existing Postgres table) -> MinIO Persistence
    (extraction metadata)

Four tiers, strongest guarantee first, each tried in order until one
applies (see template_detection.py's TemplateMode docstring for the
full picture):

  1. TRUSTED_MAPPING - caller supplies an explicit field mapping (DB/API/
     POS/ERP integrations, which already know their own schema with
     certainty) - bypasses header matching entirely.
  2. TEMPLATE_COMPLIANT - the file's headers exactly match the published
     canonical template (template_contract.py).
  3. RECOGNIZED - template_detection.py's fuzzy, multi-language synonym
     match - best-effort, not guarantee-eligible.
  4. FALLBACK - no trustworthy column structure at all; regex/NER
     extraction per row.

Zero-data-loss guarantee, and what it actually promises: the untouched
raw row is written to import_staging_rows.raw_payload_json BEFORE any
parsing is attempted, in its own try/except - nothing is EVER silently
discarded, in any tier, even on a total extraction failure for that row.
That part is unconditional, for every tier. The STRONGER promise -
every value successfully promoted to clean, typed, structured data with
nothing needing fallback - is only claimed for TRUSTED_MAPPING/
TEMPLATE_COMPLIANT tiers, and even then only actually verified per file
via IngestionSummary.is_template_compliant (computed from what actually
happened, not assumed from the tier alone - a TEMPLATE_COMPLIANT file can
still end up with is_template_compliant=False if a value failed semantic
validation). See IngestionSummary's own docstring for the exact metrics.

Field-level, not row-level, validation: a value that fails semantic
validation (row_parsing.py::validate_typed_fields()) demotes only that
one field, not the whole row - the row keeps processing with every other
field that DID validate. A row is only excluded from rows_processed (and
counted in rows_failed) when literally nothing usable came out of it at
all (no valid typed fields AND no fallback entities either).
"""
import json
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from psycopg2.extras import execute_values

from src.ai.extraction.template_detection import TemplateMode, detect_template
from src.ai.extraction.template_contract import match_canonical_template
from src.ai.extraction.row_parsing import RowParseResult, parse_mapped_row, validate_typed_fields
from src.ai.extraction.extractor import extract_entities
from src.ai.extraction.minio_persistence import build_extraction_document, upload_extraction_document
from src.ai.extraction.locale_config import get_tenant_locale

# Tiers with an actual header_mapping to parse against (typed parsing
# applies); FALLBACK has none and always goes through extract_entities().
_MAPPED_MODES = {TemplateMode.TRUSTED_MAPPING, TemplateMode.TEMPLATE_COMPLIANT, TemplateMode.RECOGNIZED}

# Tiers eligible for the 0%-loss guarantee at all - RECOGNIZED/FALLBACK
# never are, no matter how clean the actual data turns out to be, since
# their header mapping was never a certainty to begin with.
_GUARANTEE_ELIGIBLE_MODES = {TemplateMode.TRUSTED_MAPPING, TemplateMode.TEMPLATE_COMPLIANT}


@dataclass
class IngestionRowOutcome:
    row_index: int
    staging_row_id: Optional[int]
    mode: str  # TemplateMode.value
    parse_result: Optional[RowParseResult] = None
    fallback_entity_count: int = 0
    # Per-field semantic validation failures for THIS row - e.g.
    # {"quantity": "zero quantity is not a valid sale/transaction row"}.
    # Distinct from `error`: a row can have field_errors and still be
    # processed (PARTIAL), since the failed field(s) were demoted, not
    # the whole row rejected.
    field_errors: Dict[str, str] = field(default_factory=dict)
    # Reserved for a genuine row-level failure - nothing usable was
    # extracted at all, or a hard failure before extraction even ran
    # (a staging-insert DB error). None means the row was processed
    # (with or without field_errors).
    error: Optional[str] = None
    # Set only when commit_to_business_tables=True and this row's typed
    # fields were complete enough to commit past staging - see
    # _commit_row_to_business_tables()'s own docstring for exactly what
    # "complete enough" means. None means either committing wasn't
    # requested, or this row didn't qualify (still safely in staging).
    committed_table: Optional[str] = None
    committed_record_id: Optional[str] = None


@dataclass
class IngestionSummary:
    """
    total_fields_expected/total_fields_extracted/data_loss_pct are
    computed ONLY over _MAPPED_MODES rows (TRUSTED_MAPPING/
    TEMPLATE_COMPLIANT/RECOGNIZED) - a FALLBACK row has no header mapping
    to measure loss against at all, so counting it would be a category
    error (a data_loss_pct of "% of headers we never claimed to
    recognise" isn't a meaningful number). FALLBACK-mode extraction
    quality is instead visible via fallback_entity_count.

    Per row, "expected" counts only cells that were both mapped to a
    canonical field AND actually had a non-blank value in that specific
    row - a blank optional cell was never data to lose, so it doesn't
    count against the file.

    is_template_compliant is the crisp, product-facing "0% loss verified"
    signal: True only if every row processed used a guarantee-eligible
    tier (TRUSTED_MAPPING/TEMPLATE_COMPLIANT) AND every one of those rows
    validated with zero field_errors AND nothing failed outright. A
    TEMPLATE_COMPLIANT file can still end this False - the tier is a
    necessary, not sufficient, condition; this field reports what
    actually happened, not what the header row alone promised.
    """
    tenant_id: str
    job_id: str
    source_name: str
    template_mode: str
    header_coverage_ratio: float
    rows_processed: int = 0
    rows_partial: int = 0
    rows_failed: int = 0
    # Subset of rows_processed that also made it past staging into a real
    # business table (see _commit_row_to_business_tables()) - only ever
    # nonzero when commit_to_business_tables=True was passed in.
    rows_committed: int = 0
    total_fields_expected: int = 0
    total_fields_extracted: int = 0
    row_outcomes: List[IngestionRowOutcome] = field(default_factory=list)
    minio_object_key: Optional[str] = None

    @property
    def data_loss_pct(self) -> float:
        if self.total_fields_expected == 0:
            return 0.0
        return round(100.0 * (1 - self.total_fields_extracted / self.total_fields_expected), 4)

    @property
    def is_template_compliant(self) -> bool:
        if self.template_mode not in {m.value for m in _GUARANTEE_ELIGIBLE_MODES}:
            return False
        return self.rows_failed == 0 and self.rows_partial == 0 and self.rows_processed > 0


_SAVEPOINT_NAME = "ingestion_pipeline_write"


def _execute_in_savepoint(conn, sql: str, params: tuple):
    """
    Runs one write inside a SAVEPOINT, so a failure at the database level
    (a constraint violation, an encoding error Postgres rejects - e.g. a
    JSONB column can't hold an embedded NUL byte) only unwinds that one
    statement, not the whole transaction. Without this, one row's DB-level
    error leaves the transaction permanently aborted
    (psycopg2.errors.InFailedSqlTransaction), and every later statement on
    this same connection fails too - every subsequent row's writes, and
    the final job-count update - even though their content had nothing to
    do with the row that actually failed. Confirmed directly: reproduced
    against a real Postgres with a NUL byte in a cell value, which
    silently poisoned every write after it in the same file until this fix.

    A Python-level exception from the caller's own code (a parse or
    validation failure that never reaches this function at all) is a
    separate, already-handled case - this only guards actual SQL
    execution, not the row-processing logic around it.
    """
    with conn.cursor() as cursor:
        cursor.execute(f"SAVEPOINT {_SAVEPOINT_NAME};")
        try:
            cursor.execute(sql, params)
            result = cursor.fetchone() if cursor.description else None
        except Exception:
            cursor.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT_NAME};")
            raise
        else:
            cursor.execute(f"RELEASE SAVEPOINT {_SAVEPOINT_NAME};")
            return result


def _insert_staging_row(conn, tenant_id: str, job_id: str, raw_row: Dict[str, object]) -> int:
    """
    Writes the untouched row into the existing import_staging_rows table
    (schema already defines it - no migration needed for this INSERT).
    This happens before any parsing is attempted, so it is the
    zero-data-loss anchor point: whatever else fails downstream, the
    original row is already durable in Postgres.
    """
    row = _execute_in_savepoint(
        conn,
        """
        INSERT INTO import_staging_rows (tenant_id, job_id, raw_payload_json, validation_status)
        VALUES (%s, %s, %s, 'PENDING')
        RETURNING staging_row_id;
        """,
        (tenant_id, job_id, json.dumps(raw_row, ensure_ascii=False)),
    )
    return row[0]


def _update_staging_row_status(
    conn, staging_row_id: int, status: str, errors: Optional[str] = None
) -> None:
    _execute_in_savepoint(
        conn,
        """
        UPDATE import_staging_rows
        SET validation_status = %s, validation_errors = %s
        WHERE staging_row_id = %s;
        """,
        (status, errors, staging_row_id),
    )


def _insert_staging_rows_bulk(
    conn, tenant_id: str, job_id: str, raw_rows: List[Dict[str, object]]
) -> List[Optional[int]]:
    """
    Bulk equivalent of _insert_staging_row(): one multi-row INSERT instead
    of one INSERT per row. Still the zero-data-loss anchor point (every raw
    row lands here before any parsing is attempted) - batching the SQL
    doesn't change that, it only changes how many round trips it costs.
    A 51,947-row file doing one INSERT per row (each its own SAVEPOINT/
    RELEASE) is most of what made ingestion take 32-43s before any of the
    business-table work even started; this is the other half of getting
    the whole file under 20s, alongside _flush_pending_business_table_commits().

    Returns one staging_row_id per input row, in the same order, or None
    for a row whose insert failed even after the per-row fallback (see
    below) - the caller must count that row as failed and move on, never
    treat a None here as "no staging was attempted" (that case is instead
    signaled by the caller not calling this at all when conn is None).

    execute_values(..., fetch=True) is relied on to return RETURNING rows
    in the same order as the input VALUES rows - guaranteed by Postgres
    for a single INSERT statement (no JOIN/ordering ambiguity possible),
    not an assumption specific to this driver/version.
    """
    if not raw_rows:
        return []
    payloads = [(tenant_id, job_id, json.dumps(r, ensure_ascii=False)) for r in raw_rows]
    try:
        with conn.cursor() as cursor:
            cursor.execute("SAVEPOINT ingestion_pipeline_bulk_stage;")
            try:
                results = execute_values(
                    cursor,
                    "INSERT INTO import_staging_rows (tenant_id, job_id, raw_payload_json, validation_status) "
                    "VALUES %s RETURNING staging_row_id;",
                    payloads,
                    template="(%s, %s, %s, 'PENDING')",
                    fetch=True,
                )
            except Exception:
                cursor.execute("ROLLBACK TO SAVEPOINT ingestion_pipeline_bulk_stage;")
                raise
            else:
                cursor.execute("RELEASE SAVEPOINT ingestion_pipeline_bulk_stage;")
        return [row[0] for row in results]
    except Exception:  # noqa: BLE001 - fall back to per-row so one bad row (e.g. a NUL byte) doesn't lose the whole chunk
        staging_row_ids: List[Optional[int]] = []
        for raw_row in raw_rows:
            try:
                staging_row_ids.append(_insert_staging_row(conn, tenant_id, job_id, raw_row))
            except Exception:  # noqa: BLE001 - this one row's staging insert fails; it's counted failed, not staged
                staging_row_ids.append(None)
        return staging_row_ids


def _update_staging_row_statuses_bulk(conn, updates: List[Tuple[int, str, Optional[str]]]) -> None:
    """
    Bulk equivalent of _update_staging_row_status(): one multi-row UPDATE
    for a whole chunk's worth of (staging_row_id, status, errors) instead
    of one UPDATE per row. Falls back to per-row on failure, same reasoning
    as _flush_pending_business_table_commits().
    """
    if not updates:
        return
    try:
        with conn.cursor() as cursor:
            cursor.execute("SAVEPOINT ingestion_pipeline_bulk_status;")
            try:
                execute_values(
                    cursor,
                    "UPDATE import_staging_rows AS s "
                    "SET validation_status = v.status, validation_errors = v.errors "
                    "FROM (VALUES %s) AS v(staging_row_id, status, errors) "
                    "WHERE s.staging_row_id = v.staging_row_id::bigint;",
                    updates,
                )
            except Exception:
                cursor.execute("ROLLBACK TO SAVEPOINT ingestion_pipeline_bulk_status;")
                raise
            else:
                cursor.execute("RELEASE SAVEPOINT ingestion_pipeline_bulk_status;")
    except Exception:  # noqa: BLE001 - fall back to per-row so one bad value doesn't lose the whole chunk's status updates
        for staging_row_id, status, errors in updates:
            try:
                _update_staging_row_status(conn, staging_row_id, status, errors=errors)
            except Exception:  # noqa: BLE001 - this one row's status update fails; it stays PENDING rather than crashing the batch
                continue


def _update_job_counts(conn, tenant_id: str, job_id: str, processed: int, partial: int, failed: int) -> None:
    _execute_in_savepoint(
        conn,
        """
        UPDATE ingestion_jobs
        SET rows_processed = rows_processed + %s,
            rows_partial = rows_partial + %s,
            rows_failed = rows_failed + %s
        WHERE tenant_id = %s AND job_id = %s;
        """,
        (processed, partial, failed, tenant_id, job_id),
    )


def _resolve_mode(
    headers: List[str], trusted_field_mapping: Optional[Dict[str, str]]
) -> Tuple[TemplateMode, Dict[str, str], float]:
    """
    The four-tier decision, strongest guarantee first. Returns
    (mode, header_mapping, coverage_ratio). header_mapping is always
    {source_header: canonical_field}, the same shape parse_mapped_row()
    already expects regardless of which tier produced it - RECOGNIZED,
    TEMPLATE_COMPLIANT, and TRUSTED_MAPPING all hand it the identical
    shape, so no tier-specific branching is needed downstream in
    parse_mapped_row() itself.
    """
    if trusted_field_mapping:
        return TemplateMode.TRUSTED_MAPPING, dict(trusted_field_mapping), 1.0

    canonical_mapping = match_canonical_template(headers)
    if canonical_mapping is not None:
        coverage_ratio = len(canonical_mapping) / (len(headers) or 1)
        return TemplateMode.TEMPLATE_COMPLIANT, canonical_mapping, coverage_ratio

    detection = detect_template(headers)
    return detection.mode, detection.header_mapping, detection.coverage_ratio


def _process_mapped_row(
    raw_row: Dict[str, object], header_mapping: Dict[str, str], tenant_id: str,
    decimal_style: Optional[str], day_first: Optional[bool],
) -> Tuple[RowParseResult, Dict[str, str], int]:
    """
    TRUSTED_MAPPING/TEMPLATE_COMPLIANT/RECOGNIZED tiers: typed parsing +
    field-level validation. Returns (result, field_errors,
    row_fields_expected) with failed fields already dropped from
    result.typed_fields. Raises ValueError if nothing usable survived at
    all (see process_records()'s own docstring for what "nothing usable"
    means and why that's still a genuine row failure).
    """
    result = parse_mapped_row(raw_row, header_mapping, tenant_id, decimal_style, day_first)

    # Spec S12's "Validate values" step, field-level: a cell can parse
    # cleanly (a real number, a real date shape) and still be
    # semantically wrong - a negative price, a zero quantity, a year
    # outside any plausible invoice range. Only the specific bad field is
    # demoted; every other field in the row keeps its clean, typed value.
    field_errors = validate_typed_fields(result)
    for bad_field in field_errors:
        result.typed_fields.pop(bad_field, None)
        result.field_confidence.pop(bad_field, None)

    row_fields_expected = sum(
        1 for source_header, value in raw_row.items()
        if source_header in header_mapping and value is not None and str(value).strip() != ""
    )

    if not result.typed_fields and not result.fallback_entities:
        reason = "; ".join(f"{k}: {v}" for k, v in field_errors.items()) or "no fields could be extracted"
        raise ValueError(reason)

    return result, field_errors, row_fields_expected


def _process_fallback_row(
    raw_row: Dict[str, object], tenant_id: str, redis_client, conn,
    decimal_style: Optional[str], day_first: Optional[bool],
) -> RowParseResult:
    """FALLBACK tier: regex/NER extraction, no header mapping to validate against."""
    row_text = " ".join(str(v) for v in raw_row.values() if v is not None)
    entities = extract_entities(
        row_text, tenant_id=tenant_id, redis_client=redis_client, conn=conn,
        decimal_style=decimal_style, day_first=day_first,
    )
    # Fold fallback-mode entities into the same RowParseResult shape used
    # by the mapped tiers, so build_extraction_document() and downstream
    # consumers don't need a second code path.
    result = RowParseResult(tenant_id=tenant_id)
    result.fallback_entities = entities
    result.unmapped_columns = list(raw_row.keys())
    for entity in entities:
        result.field_confidence[f"row:{entity.entity_type}"] = 0.5
    return result


# The one set of typed_fields this pipeline currently knows how to commit
# past staging: template_contract.py's canonical sales-transaction shape.
# A row missing any of these (e.g. a PARTIAL row that lost unit_price to
# field-level validation) is left safely in import_staging_rows rather
# than committed with a guessed/default value - "commit what's complete,
# leave the rest in staging for a human" mirrors the field-level PARTIAL
# philosophy this module already applies to validation.
_TRANSACTION_REQUIRED_FIELDS = ("product_name", "quantity", "unit_price", "currency", "transaction_date")


def _find_existing_product(conn, tenant_id: str, product_name: str) -> Optional[str]:
    """
    Exact-match lookup only (case-sensitive, English name only) - this is
    a deliberate first-pass simplification, not a claim of real catalog
    matching. src/ai/extraction/catalog_matching.py already exists for a
    different job (finding known product mentions inside FALLBACK-tier
    free text) and isn't a fit here: this needs to match one row's
    already-isolated product_name field against products.product_name,
    not scan prose for mentions. A real fuzzy/multilingual match (reusing
    src/ai/pricing/matching.py's similarity() would be the natural
    candidate) is follow-up work, flagged here rather than silently
    assumed solved.
    """
    result = _execute_in_savepoint(
        conn,
        "SELECT product_id FROM products "
        "WHERE tenant_id = %s AND product_name->>'en' = %s AND deleted_at IS NULL "
        "LIMIT 1;",
        (tenant_id, product_name),
    )
    return str(result[0]) if result else None


def _create_product(conn, tenant_id: str, product_name: str, unit_price: str, currency: str) -> str:
    result = _execute_in_savepoint(
        conn,
        "INSERT INTO products (tenant_id, product_name, current_price, currency, source) "
        "VALUES (%s, %s::jsonb, %s, %s, 'IMPORTED') "
        "RETURNING product_id;",
        (tenant_id, json.dumps({"en": product_name}, ensure_ascii=False), unit_price, currency),
    )
    return str(result[0])


def _match_or_create_product(
    conn, tenant_id: str, product_name: str, unit_price: str, currency: str, product_cache: Dict[str, str]
) -> str:
    """
    product_cache is one dict per process_records() call (not shared
    across calls/tenants) - avoids a repeat SELECT/INSERT for every row
    of a file that names the same product hundreds or thousands of times
    (the common case), at zero cross-request staleness risk since it
    never outlives one call.
    """
    cache_key = product_name.strip().lower()
    if cache_key in product_cache:
        return product_cache[cache_key]
    product_id = _find_existing_product(conn, tenant_id, product_name)
    if product_id is None:
        product_id = _create_product(conn, tenant_id, product_name, unit_price, currency)
    product_cache[cache_key] = product_id
    return product_id


def _prepare_business_table_commit(
    conn, tenant_id: str, staging_row_id: int, typed_fields: Dict[str, str], product_cache: Dict[str, str]
) -> Optional[dict]:
    """
    The staging -> real-table handoff import_staging_rows.committed_table/
    committed_record_id were added for (see this module's own docstring's
    pipeline diagram) but that nothing in this codebase ever performed -
    confirmed by grep before writing this: no INSERT into products or
    transactions existed anywhere in src/ai/extraction/, so every
    successfully-ingested row stopped at staging forever, no matter how
    fast or clean the ingestion itself was.

    Only prepares the one row shape this pipeline can currently interpret
    with confidence: template_contract.py's canonical sales-transaction
    fields (_TRANSACTION_REQUIRED_FIELDS). Matches/creates the named
    product immediately (product_cache makes repeat names near-free - see
    its own docstring), but does NOT write the transaction/staging-update
    yet - that happens in one bulk statement per batch, in
    _flush_pending_business_table_commits(), not once per row. A 51,947-
    row file doing one INSERT+UPDATE pair per row (each its own
    SAVEPOINT/RELEASE round trip) measured at 67.6s; batching them is what
    gets this under the 20s target without changing what gets written.

    Returns a dict of everything the batch flush needs, or None if
    typed_fields doesn't have every required field (a PARTIAL row missing
    one of them, or a FALLBACK-tier row with no typed_fields at all) -
    that row simply stays in staging, exactly as before this function
    existed, rather than being committed with a guessed value.
    """
    if not all(typed_fields.get(f) for f in _TRANSACTION_REQUIRED_FIELDS):
        return None

    product_name = typed_fields["product_name"]
    quantity = typed_fields["quantity"]
    unit_price = typed_fields["unit_price"]
    currency = typed_fields["currency"]
    transaction_date = typed_fields["transaction_date"]

    product_id = _match_or_create_product(conn, tenant_id, product_name, unit_price, currency, product_cache)

    # Generated client-side (not via INSERT...RETURNING) specifically so the
    # bulk INSERT below never needs to read anything back - the same id is
    # already known for both the transactions row and the staging-row
    # UPDATE that references it.
    transaction_id = str(uuid.uuid4())
    total_price = f"{float(quantity) * float(unit_price):.4f}"

    return {
        "staging_row_id": staging_row_id,
        "transaction_id": transaction_id,
        "transaction_row": (
            transaction_id, tenant_id, product_id, quantity, unit_price, total_price, currency, transaction_date,
        ),
    }


def _flush_pending_business_table_commits(conn, pending: List[dict]) -> List[int]:
    """
    Bulk-writes everything _prepare_business_table_commit() queued up since
    the last flush: one multi-row INSERT into transactions, one multi-row
    UPDATE of import_staging_rows, instead of one round trip pair per row.
    Returns the staging_row_ids that were actually committed - all of
    `pending` on the bulk-success path, a possibly-smaller subset on the
    per-row fallback path (see below).

    Both statements run inside ONE savepoint for the whole batch, not one
    per row - trades the old per-row failure isolation (a single bad
    transaction value could only ever fail that one row before) for bulk
    speed. Accepted because everything in `pending` already passed this
    row's own field-level semantic validation before reaching here; a
    DB-level rejection at this point (e.g. a value genuinely outside a
    column's CHECK constraint that validation didn't already catch) is the
    rare case, not the common one. On that rare case, falls back to
    committing this batch's rows one at a time (still each in its own
    SAVEPOINT via _execute_in_savepoint) so one bad row in a batch still
    can't take the rest of the batch down with it - just slower for that
    one batch, not silently lossy.
    """
    if not pending:
        return []
    try:
        with conn.cursor() as cursor:
            cursor.execute("SAVEPOINT ingestion_pipeline_bulk_commit;")
            try:
                execute_values(
                    cursor,
                    "INSERT INTO transactions "
                    "(transaction_id, tenant_id, product_id, quantity_sold, unit_price, total_price, "
                    " original_currency, transaction_date, sale_source) VALUES %s",
                    [(*p["transaction_row"], "FILE_IMPORT") for p in pending],
                )
                execute_values(
                    cursor,
                    "UPDATE import_staging_rows AS s "
                    "SET validation_status = 'COMMITTED', committed_table = 'transactions', "
                    "    committed_record_id = v.transaction_id::uuid "
                    "FROM (VALUES %s) AS v(staging_row_id, transaction_id) "
                    "WHERE s.staging_row_id = v.staging_row_id::bigint;",
                    [(p["staging_row_id"], p["transaction_id"]) for p in pending],
                )
            except Exception:
                cursor.execute("ROLLBACK TO SAVEPOINT ingestion_pipeline_bulk_commit;")
                raise
            else:
                cursor.execute("RELEASE SAVEPOINT ingestion_pipeline_bulk_commit;")
        return [p["staging_row_id"] for p in pending]
    except Exception:  # noqa: BLE001 - fall back to per-row so one bad value doesn't lose the whole batch
        committed_staging_row_ids = []
        for p in pending:
            try:
                _execute_in_savepoint(
                    conn,
                    "INSERT INTO transactions "
                    "(transaction_id, tenant_id, product_id, quantity_sold, unit_price, total_price, "
                    " original_currency, transaction_date, sale_source) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'FILE_IMPORT');",
                    p["transaction_row"],
                )
                _execute_in_savepoint(
                    conn,
                    "UPDATE import_staging_rows "
                    "SET validation_status = 'COMMITTED', committed_table = 'transactions', committed_record_id = %s "
                    "WHERE staging_row_id = %s;",
                    (p["transaction_id"], p["staging_row_id"]),
                )
            except Exception:  # noqa: BLE001 - this one row's commit fails, it stays in staging; the rest of the batch still lands
                continue
            else:
                committed_staging_row_ids.append(p["staging_row_id"])
        return committed_staging_row_ids


def process_records(
    tenant_id: str,
    job_id: str,
    source_name: str,
    headers: List[str],
    rows: List[Dict[str, object]],
    trusted_field_mapping: Optional[Dict[str, str]] = None,
    conn=None,
    redis_client=None,
    minio_client=None,
    commit_every: Optional[int] = None,
    commit_to_business_tables: bool = False,
) -> IngestionSummary:
    """
    Runs the full pipeline for one uploaded file or one batch of records
    from a live integration.

    trusted_field_mapping: pass a {source_field: canonical_field} mapping
    when the caller already knows its own schema with certainty (a DB
    query with known column names, a POS/ERP API's documented response
    shape) - this is the TRUSTED_MAPPING tier (item 4 of the extraction
    refactor): it skips header-matching entirely rather than making a
    perfectly well-typed database row or JSON record fight through a
    fuzzy synonym table meant for messy human-typed spreadsheets.

    `conn`, `redis_client`, and `minio_client` are all optional so this
    can run in a dry-run/preview mode (e.g. showing the user what would
    happen before committing) with no side effects: pass None for any of
    them to skip that stage. In production, all three should be supplied
    for the full zero-data-loss + catalog-matching + MinIO-provenance
    pipeline described in the module docstring.

    Locale (date-order, decimal separator) is resolved once here from
    companies.country_code via locale_config.get_tenant_locale(), not
    per-row - avoids one extra DB query per row. Falls back to the
    global EXTRACTION_* env-var defaults if conn is omitted or the
    tenant row isn't found. This resolves the tenant's primary
    registered country only; a tenant operating in more than one
    country (companies.operating_countries) is not split per-file by
    country here - there's no per-file country field in the current
    schema to resolve against instead.

    commit_every: opt-in, default None (unset preserves the exact original
    behavior - one implicit transaction for the whole file, the caller
    commits or rolls back everything at once; some callers rely on this,
    e.g. test_extraction_ingestion_pipeline_integration_db.py's own `conn`
    fixture rolls back after every test for cleanup - passing commit_every
    there would leak committed rows into the test database). When set (and
    `conn` is supplied), commits job-count progress to the database every
    `commit_every` rows instead of holding tens of thousands of per-row
    SAVEPOINTs in one uncommitted transaction. This addresses a real,
    measured scaling cliff (PENDING_ACTIONS.md #43 / src/ai/extraction/
    SCALING.md): a 51,947-row file took 8.5 hours in one transaction vs.
    7 seconds of pure compute, traced to Postgres's subtransaction-cache
    degrading once a single transaction accumulates that many SAVEPOINTs.
    Periodic commits reset that count before it matters. Tradeoff: a crash
    mid-file now loses at most the current uncommitted batch, not the
    whole file - each row's own SAVEPOINT-protected write is still
    individually safe either way, and the zero-data-loss guarantee (the
    raw row lands in import_staging_rows before parsing is attempted) is
    unaffected by this parameter either way.

    commit_to_business_tables: opt-in, default False (unset preserves the
    exact original behavior - every row stops at import_staging_rows, the
    same "landed but never committed" gap this parameter exists to close).
    When True (and `conn` is supplied), each row whose typed_fields cover
    the full canonical sales-transaction shape (_TRANSACTION_REQUIRED_FIELDS)
    is additionally committed into products (matched-or-created) and
    transactions - see _commit_row_to_business_tables()'s own docstring
    for exactly which rows qualify and what "commit" means for the ones
    that don't. Same reasoning as commit_every for defaulting off: tests
    whose `conn` fixture rolls back for cleanup (rather than using
    commit_every) must not have this default on either, or every test run
    would leak real products/transactions rows into the test database.
    """
    decimal_style, day_first, default_currency = None, None, None
    if conn is not None:
        locale = get_tenant_locale(conn, tenant_id)
        if locale is not None:
            decimal_style, day_first = locale.decimal_style, locale.date_day_first
            default_currency = locale.primary_currency or None

    mode, header_mapping, coverage_ratio = _resolve_mode(headers, trusted_field_mapping)

    # Scoped to the FILE, not the row: only when no column was recognized
    # as currency at all (e.g. mocks/Electronics_For_Test.xlsx, a POS
    # export with no currency column whatsoever) does a missing currency
    # get the tenant's own primary_currency filled in below. A row whose
    # file DOES have a currency column but left this one cell blank/invalid
    # must still fall through to "incomplete, stays in staging" - silently
    # substituting a default there would hide a real data-quality problem
    # instead of surfacing it, the opposite of this module's field-level
    # PARTIAL philosophy.
    apply_default_currency = (
        default_currency is not None and mode in _MAPPED_MODES and "currency" not in header_mapping.values()
    )

    summary = IngestionSummary(
        tenant_id=tenant_id,
        job_id=job_id,
        source_name=source_name,
        template_mode=mode.value,
        header_coverage_ratio=coverage_ratio,
    )

    parse_results: List[RowParseResult] = []
    flushed_processed = flushed_partial = flushed_failed = 0
    product_cache: Dict[str, str] = {}
    pending_commits: List[dict] = []

    # Chunked, not per-row: _insert_staging_rows_bulk()/_update_staging_row_statuses_bulk()/
    # _flush_pending_business_table_commits() each do one multi-row
    # statement per chunk instead of one statement per row - this is what
    # brought a 51,947-row file from 67.6s down to under the 20s target
    # (see this function's own module-level performance note in
    # SCALING.md). Chunk size follows commit_every when the caller set
    # one (so a chunk boundary is also a commit boundary, same cadence as
    # before); with commit_every unset, chunks are still batched for SQL
    # efficiency at a fixed internal size, but nothing is committed until
    # the caller commits - unchanged "one implicit transaction" contract.
    chunk_size = commit_every if commit_every else 500
    status_updates: List[Tuple[int, str, Optional[str]]] = []

    for chunk_start in range(0, len(rows), chunk_size):
        chunk = rows[chunk_start:chunk_start + chunk_size]
        staging_row_ids = _insert_staging_rows_bulk(conn, tenant_id, job_id, chunk) if conn is not None else [None] * len(chunk)

        for offset, raw_row in enumerate(chunk):
            i = chunk_start + offset
            staging_row_id = staging_row_ids[offset]

            if conn is not None and staging_row_id is None:
                summary.rows_failed += 1
                summary.row_outcomes.append(
                    IngestionRowOutcome(row_index=i, staging_row_id=None, mode=mode.value, error="staging insert failed")
                )
                continue

            try:
                if mode in _MAPPED_MODES:
                    result, field_errors, row_fields_expected = _process_mapped_row(
                        raw_row, header_mapping, tenant_id, decimal_style, day_first
                    )
                    summary.total_fields_expected += row_fields_expected
                    summary.total_fields_extracted += len(result.typed_fields)
                else:
                    result = _process_fallback_row(raw_row, tenant_id, redis_client, conn, decimal_style, day_first)
                    field_errors = {}

                if apply_default_currency and not result.typed_fields.get("currency"):
                    # The file itself carries no currency column (e.g. a POS
                    # export whose amounts are implicitly in the business's
                    # own home currency - confirmed live against
                    # mocks/Electronics_For_Test.xlsx, which has none).
                    # Falls back to companies.primary_currency rather than
                    # leaving every row short of _TRANSACTION_REQUIRED_FIELDS
                    # forever. Applied AFTER total_fields_extracted is
                    # counted above, deliberately: this is an inferred
                    # default, not something the file itself provided, so it
                    # must never inflate the data_loss_pct/extraction-
                    # accuracy metrics.
                    result.typed_fields["currency"] = default_currency

                parse_results.append(result)
                summary.rows_processed += 1
                if field_errors:
                    summary.rows_partial += 1

                outcome = IngestionRowOutcome(
                    row_index=i,
                    staging_row_id=staging_row_id,
                    mode=mode.value,
                    parse_result=result,
                    fallback_entity_count=len(result.fallback_entities),
                    field_errors=field_errors,
                )
                summary.row_outcomes.append(outcome)

                if conn is not None and staging_row_id is not None:
                    status = "PARTIAL" if field_errors else "VALID"
                    errors_json = json.dumps(field_errors) if field_errors else None
                    status_updates.append((staging_row_id, status, errors_json))

                    if commit_to_business_tables:
                        try:
                            prepared = _prepare_business_table_commit(
                                conn, tenant_id, staging_row_id, result.typed_fields, product_cache
                            )
                        except Exception as e:  # noqa: BLE001 - a product match/create failure leaves the row safely in staging
                            prepared = None
                            outcome.error = f"business-table commit failed (row stays in staging): {e}"
                        if prepared is not None:
                            prepared["outcome"] = outcome
                            pending_commits.append(prepared)

            except Exception as e:  # noqa: BLE001 - one bad row must not sink the whole file
                summary.rows_failed += 1
                summary.row_outcomes.append(
                    IngestionRowOutcome(
                        row_index=i,
                        staging_row_id=staging_row_id,
                        mode=mode.value,
                        error=str(e),
                    )
                )
                if conn is not None and staging_row_id is not None:
                    status_updates.append((staging_row_id, "INVALID", str(e)))

        if conn is not None:
            _update_staging_row_statuses_bulk(conn, status_updates)
            status_updates = []

            if pending_commits:
                committed_ids = set(_flush_pending_business_table_commits(conn, pending_commits))
                for p in pending_commits:
                    if p["staging_row_id"] in committed_ids:
                        summary.rows_committed += 1
                        p["outcome"].committed_table = "transactions"
                        p["outcome"].committed_record_id = p["transaction_id"]
                pending_commits = []

            if commit_every:
                _update_job_counts(
                    conn, tenant_id, job_id,
                    summary.rows_processed - flushed_processed,
                    summary.rows_partial - flushed_partial,
                    summary.rows_failed - flushed_failed,
                )
                conn.commit()
                flushed_processed = summary.rows_processed
                flushed_partial = summary.rows_partial
                flushed_failed = summary.rows_failed

    if conn is not None:
        _update_job_counts(
            conn, tenant_id, job_id,
            summary.rows_processed - flushed_processed,
            summary.rows_partial - flushed_partial,
            summary.rows_failed - flushed_failed,
        )
        if commit_every:
            conn.commit()

    if minio_client is not None and parse_results:
        document = build_extraction_document(tenant_id, job_id, source_name, parse_results)
        summary.minio_object_key = upload_extraction_document(
            minio_client, document, tenant_id, job_id
        )

    return summary

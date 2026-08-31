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
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

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


def _stage_row_or_error(conn, tenant_id: str, job_id: str, raw_row: Dict[str, object]) -> Tuple[Optional[int], Optional[str]]:
    """Returns (staging_row_id, None) on success, or (None, error_message) if the INSERT itself failed."""
    if conn is None:
        return None, None
    try:
        return _insert_staging_row(conn, tenant_id, job_id, raw_row), None
    except Exception as e:  # noqa: BLE001 - a staging-write failure must not stop the batch
        return None, f"staging insert failed: {e}"


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
    """
    decimal_style, day_first = None, None
    if conn is not None:
        locale = get_tenant_locale(conn, tenant_id)
        if locale is not None:
            decimal_style, day_first = locale.decimal_style, locale.date_day_first

    mode, header_mapping, coverage_ratio = _resolve_mode(headers, trusted_field_mapping)
    summary = IngestionSummary(
        tenant_id=tenant_id,
        job_id=job_id,
        source_name=source_name,
        template_mode=mode.value,
        header_coverage_ratio=coverage_ratio,
    )

    parse_results: List[RowParseResult] = []
    flushed_processed = flushed_partial = flushed_failed = 0

    for i, raw_row in enumerate(rows):
        staging_row_id, staging_error = _stage_row_or_error(conn, tenant_id, job_id, raw_row)
        if staging_error is not None:
            summary.rows_failed += 1
            summary.row_outcomes.append(
                IngestionRowOutcome(row_index=i, staging_row_id=None, mode=mode.value, error=staging_error)
            )
        else:
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
                    _update_staging_row_status(conn, staging_row_id, status, errors=errors_json)

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
                    _update_staging_row_status(conn, staging_row_id, "INVALID", errors=str(e))

        if commit_every and conn is not None and (i + 1) % commit_every == 0:
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

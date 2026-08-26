"""
CEOPRO AI - Ingestion Pipeline Orchestrator.
Implements the full target architecture end-to-end for a single uploaded
file, at zero infrastructure cost:

    Input File -> Template Detection -> Structured Parsing / Fallback
    Extraction -> Normalization -> Catalog Matching -> Canonical
    Extraction Output -> import_staging_rows (existing Postgres table,
    zero schema change) -> MinIO Persistence (extraction metadata)

Zero-data-loss guarantee: the untouched raw row is written to
import_staging_rows.raw_payload_json BEFORE any parsing is attempted, in
its own try/except. A row that crashes every extraction path still has
its original data sitting in Postgres with validation_status='INVALID'
and the error recorded - nothing is ever silently dropped, even on a
total extraction failure for that row.
"""
import json
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from src.ai.extraction.template_detection import TemplateMode, detect_template
from src.ai.extraction.row_parsing import RowParseResult, parse_mapped_row
from src.ai.extraction.extractor import extract_entities
from src.ai.extraction.minio_persistence import build_extraction_document, upload_extraction_document


@dataclass
class IngestionRowOutcome:
    row_index: int
    staging_row_id: Optional[int]
    mode: str  # "STRICT" or "FALLBACK"
    parse_result: Optional[RowParseResult] = None
    fallback_entity_count: int = 0
    error: Optional[str] = None


@dataclass
class IngestionSummary:
    tenant_id: str
    job_id: str
    source_filename: str
    template_mode: str
    header_coverage_ratio: float
    rows_processed: int = 0
    rows_failed: int = 0
    row_outcomes: List[IngestionRowOutcome] = field(default_factory=list)
    minio_object_key: Optional[str] = None


def _insert_staging_row(conn, tenant_id: str, job_id: str, raw_row: Dict[str, object]) -> int:
    """
    Writes the untouched row into the existing import_staging_rows table
    (schema already defines it - no migration needed). This happens
    before any parsing is attempted, so it is the zero-data-loss anchor
    point: whatever else fails downstream, the original row is already
    durable in Postgres.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO import_staging_rows (tenant_id, job_id, raw_payload_json, validation_status)
            VALUES (%s, %s, %s, 'PENDING')
            RETURNING staging_row_id;
            """,
            (tenant_id, job_id, json.dumps(raw_row, ensure_ascii=False)),
        )
        return cursor.fetchone()[0]


def _update_staging_row_status(
    conn, staging_row_id: int, status: str, errors: Optional[str] = None
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE import_staging_rows
            SET validation_status = %s, validation_errors = %s
            WHERE staging_row_id = %s;
            """,
            (status, errors, staging_row_id),
        )


def _update_job_counts(conn, tenant_id: str, job_id: str, processed: int, failed: int) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE ingestion_jobs
            SET rows_processed = rows_processed + %s,
                rows_failed = rows_failed + %s
            WHERE tenant_id = %s AND job_id = %s;
            """,
            (processed, failed, tenant_id, job_id),
        )


def process_file(
    tenant_id: str,
    job_id: str,
    source_filename: str,
    headers: List[str],
    rows: List[Dict[str, object]],
    conn=None,
    redis_client=None,
    minio_client=None,
) -> IngestionSummary:
    """
    Runs the full pipeline for one uploaded file.

    `conn`, `redis_client`, and `minio_client` are all optional so this
    can run in a dry-run/preview mode (e.g. showing the user what would
    happen before committing) with no side effects: pass None for any of
    them to skip that stage. In production, all three should be supplied
    for the full zero-data-loss + catalog-matching + MinIO-provenance
    pipeline described in the module docstring.
    """
    detection = detect_template(headers)
    summary = IngestionSummary(
        tenant_id=tenant_id,
        job_id=job_id,
        source_filename=source_filename,
        template_mode=detection.mode.value,
        header_coverage_ratio=detection.coverage_ratio,
    )

    parse_results: List[RowParseResult] = []

    for i, raw_row in enumerate(rows):
        staging_row_id = None
        if conn is not None:
            try:
                staging_row_id = _insert_staging_row(conn, tenant_id, job_id, raw_row)
            except Exception as e:  # noqa: BLE001 - a staging-write failure must not stop the batch
                summary.rows_failed += 1
                summary.row_outcomes.append(
                    IngestionRowOutcome(
                        row_index=i,
                        staging_row_id=None,
                        mode=detection.mode.value,
                        error=f"staging insert failed: {e}",
                    )
                )
                continue

        try:
            if detection.mode == TemplateMode.STRICT:
                result = parse_mapped_row(raw_row, detection.header_mapping, tenant_id)
                parse_results.append(result)
                outcome = IngestionRowOutcome(
                    row_index=i,
                    staging_row_id=staging_row_id,
                    mode="STRICT",
                    parse_result=result,
                    fallback_entity_count=len(result.fallback_entities),
                )
            else:
                row_text = " ".join(str(v) for v in raw_row.values() if v is not None)
                entities = extract_entities(
                    row_text, tenant_id=tenant_id, redis_client=redis_client, conn=conn
                )
                # Fold fallback-mode entities into the same RowParseResult
                # shape used by STRICT mode, so build_extraction_document()
                # and downstream consumers don't need a second code path.
                result = RowParseResult(tenant_id=tenant_id)
                result.fallback_entities = entities
                result.unmapped_columns = list(raw_row.keys())
                for entity in entities:
                    result.field_confidence[f"row:{entity.entity_type}"] = 0.5
                parse_results.append(result)
                outcome = IngestionRowOutcome(
                    row_index=i,
                    staging_row_id=staging_row_id,
                    mode="FALLBACK",
                    parse_result=result,
                    fallback_entity_count=len(entities),
                )

            summary.rows_processed += 1
            summary.row_outcomes.append(outcome)
            if conn is not None and staging_row_id is not None:
                _update_staging_row_status(conn, staging_row_id, "VALID")

        except Exception as e:  # noqa: BLE001 - one bad row must not sink the whole file
            summary.rows_failed += 1
            summary.row_outcomes.append(
                IngestionRowOutcome(
                    row_index=i,
                    staging_row_id=staging_row_id,
                    mode=detection.mode.value,
                    error=str(e),
                )
            )
            if conn is not None and staging_row_id is not None:
                _update_staging_row_status(conn, staging_row_id, "INVALID", errors=str(e))

    if conn is not None:
        _update_job_counts(conn, tenant_id, job_id, summary.rows_processed, summary.rows_failed)

    if minio_client is not None and parse_results:
        document = build_extraction_document(tenant_id, job_id, source_filename, parse_results)
        summary.minio_object_key = upload_extraction_document(
            minio_client, document, tenant_id, job_id
        )

    return summary

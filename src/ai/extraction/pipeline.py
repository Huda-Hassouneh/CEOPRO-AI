"""
CEOPRO AI - Extraction Pipeline Orchestration (spec S15).
Loads 'Pending' news_record/social_mention rows -> runs the canonical
extractor (regex tier + Redis-cached catalog tier, extraction/extractor.py)
against each -> persists results to extracted_entity -> marks the source row
'Processed' or 'Failed' (spec S12: never silently discard invalid data),
mirroring rag/pipeline.py's ingest_pending_documents() convention.

redis_client is optional and caller-injected, same convention as
ingestion_pipeline.py's process_file() and rag/'s minio_client - when not
supplied, extract_entities() runs regex-only (no catalog matching), not an
error, per its own "all three of tenant_id/redis_client/conn or none of
them" contract.

Deliberately writes no evidence_records: bulk entity extraction is an
annotation step over raw text, not itself a user-facing conclusion - same
reasoning sentiment/pipeline.py's classify_and_store_reviews() already
documents for bulk sentiment labeling.

Each record's DB work runs inside a SAVEPOINT (same pattern as
ingestion_pipeline.py, found necessary by the same class of bug there):
without it, a record whose extracted entity value Postgres rejects at the
database level (extracted_entity.entity_value is VARCHAR(512) - a long
catalog name, or several regex matches merged into one long span, can
legitimately exceed that) leaves the connection transaction-aborted. The
except block's own recovery write (marking that record 'Failed') would
then *also* fail on the poisoned connection, an uncaught exception that
crashes the whole function - not just that one record, every record still
pending in the same batch, silently left 'Pending' forever with no error
surfaced anywhere. Reproduced directly against a real Postgres before this
fix: a 521-character catalog match crashed extract_and_store_news_records()
with psycopg2.errors.InFailedSqlTransaction, leaving even a second,
perfectly valid record in the same batch unprocessed.
"""

import logging

from src.ai.extraction import data_access, evidence
from src.ai.extraction.extractor import extract_entities

logger = logging.getLogger("CEOPRO_AI_EXTRACTION_PIPELINE")

_SAVEPOINT_NAME = "extraction_pipeline_record"


def _process_one_record(conn, extract_fn, persist_fn, mark_status_fn, record_id: str) -> bool:
    """
    Runs one record's extract-and-persist inside a SAVEPOINT, rolling back
    to it (not the whole transaction) on any failure, so the connection is
    still usable for the caller's own recovery write (marking the record
    'Failed') and for every subsequent record in the batch. Returns True
    on success, False on failure (already logged and marked 'Failed' by
    the time this returns).
    """
    with conn.cursor() as cursor:
        cursor.execute(f"SAVEPOINT {_SAVEPOINT_NAME};")
    try:
        entities = extract_fn()
        persist_fn(entities)
    except Exception as err:
        logger.error(f"Failed to extract entities for {record_id}: {err}")
        with conn.cursor() as cursor:
            cursor.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT_NAME};")
        mark_status_fn("Failed")
        return False
    else:
        with conn.cursor() as cursor:
            cursor.execute(f"RELEASE SAVEPOINT {_SAVEPOINT_NAME};")
        mark_status_fn("Processed")
        return True


def extract_and_store_news_records(conn, tenant_id: str, redis_client=None, limit: int = 100) -> int:
    pending = data_access.load_pending_news_records(conn, tenant_id, limit)
    processed_count = 0

    for record in pending:
        ok = _process_one_record(
            conn,
            extract_fn=lambda r=record: extract_entities(r["body_text"], tenant_id=tenant_id, redis_client=redis_client, conn=conn),
            persist_fn=lambda entities, r=record: evidence.insert_extracted_entities(conn, tenant_id, "news_record", r["news_id"], entities),
            mark_status_fn=lambda status, r=record: data_access.mark_news_record_status(conn, r["news_id"], status),
            record_id=f"news_record={record['news_id']}",
        )
        if ok:
            processed_count += 1

    conn.commit()
    logger.info(f"News extraction complete for tenant={tenant_id}: {processed_count}/{len(pending)} processed")
    return processed_count


def extract_and_store_social_mentions(conn, tenant_id: str, redis_client=None, limit: int = 100) -> int:
    pending = data_access.load_pending_social_mentions(conn, tenant_id, limit)
    processed_count = 0

    for record in pending:
        ok = _process_one_record(
            conn,
            extract_fn=lambda r=record: extract_entities(r["mention_text"], tenant_id=tenant_id, redis_client=redis_client, conn=conn),
            persist_fn=lambda entities, r=record: evidence.insert_extracted_entities(conn, tenant_id, "social_mention", r["mention_id"], entities),
            mark_status_fn=lambda status, r=record: data_access.mark_social_mention_status(conn, r["mention_id"], status),
            record_id=f"social_mention={record['mention_id']}",
        )
        if ok:
            processed_count += 1

    conn.commit()
    logger.info(f"Social mention extraction complete for tenant={tenant_id}: {processed_count}/{len(pending)} processed")
    return processed_count

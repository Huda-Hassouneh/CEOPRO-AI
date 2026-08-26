"""
CEOPRO AI - MinIO Persistence Layer for Extraction Results.
Enforces an immutable object-storage archiving layer to record pipeline extraction 
output without modifying relational database schema boundaries. Formats structured 
JSON records partitioned cleanly by tenant and ingestion job parameters.
"""
import io
import json
import uuid
from datetime import datetime, timezone
from typing import List

from minio import Minio
from minio.error import S3Error

from src.ai.extraction.row_parsing import RowParseResult

EXTRACTION_RESULTS_BUCKET = "ceopro-extraction-results"


def _entity_to_dict(entity) -> dict:
    return {
        "entity_type": entity.entity_type,
        "text": entity.text,
        "start": entity.start,
        "end": entity.end,
        "normalized_value": entity.normalized_value,
    }


def _row_result_to_dict(result: RowParseResult) -> dict:
    return {
        "typed_fields": result.typed_fields,
        # Provenance: raw cell text behind each typed_fields entry, keyed
        # the same way, so a normalized value can always be traced back to
        # what the source row actually said - previously only the
        # normalized value was persisted here, which defeated the
        # traceability requirement (original file -> ... -> normalized
        # value -> final artifact) at the last hop.
        "raw_fields": result.raw_fields,
        "field_confidence": result.field_confidence,
        "fallback_entities": [_entity_to_dict(e) for e in result.fallback_entities],
        "unmapped_columns": result.unmapped_columns,
    }


def build_extraction_document(
    tenant_id: str,
    ingestion_job_id: str,
    source_filename: str,
    row_results: List[RowParseResult],
) -> dict:
    """
    Assembles a micro-batch of row execution traces into a single atomic JSON document payload.
    Exposes high-level tracking counts for downstream trace UI validation dashboards.
    """
    now = datetime.now(timezone.utc).isoformat()
    rows = [_row_result_to_dict(r) for r in row_results]
    verified_field_count = sum(
        1 for r in row_results for c in r.field_confidence.values() if c >= 1.0
    )
    estimated_field_count = sum(
        1 for r in row_results for c in r.field_confidence.values() if c < 1.0
    )
    return {
        "document_type": "extraction_result",
        "schema_version": 1,
        "tenant_id": tenant_id,
        "ingestion_job_id": ingestion_job_id,
        "source_filename": source_filename,
        "created_at": now,
        "row_count": len(row_results),
        "verified_field_count": verified_field_count,
        "estimated_field_count": estimated_field_count,
        "rows": rows,
    }


def _object_key(tenant_id: str, ingestion_job_id: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{tenant_id}/{ingestion_job_id}/{ts}_{uuid.uuid4().hex}.json"


def _ensure_bucket(client: Minio, bucket: str) -> None:
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def upload_extraction_document(
    client: Minio,
    document: dict,
    tenant_id: str,
    ingestion_job_id: str,
    bucket: str = EXTRACTION_RESULTS_BUCKET,
) -> str:
    """
    Streams a structural JSON document into object storage under an immutable tracking path. 
    Guarantees no file clobbering or write-lock contention using unique transaction keys.
    """
    _ensure_bucket(client, bucket)
    key = _object_key(tenant_id, ingestion_job_id)
    payload = json.dumps(document, ensure_ascii=False, indent=None).encode("utf-8")
    try:
        client.put_object(
            bucket_name=bucket,
            object_name=key,
            data=io.BytesIO(payload),
            length=len(payload),
            content_type="application/json",
        )
    except S3Error as e:
        raise RuntimeError(f"Failed to persist extraction document to MinIO: {e}") from e
    return key

"""
KEEL - MinIO Persistence Layer for Extraction Results.
Enforces an immutable object-storage archiving layer to record pipeline extraction 
output without modifying relational database schema boundaries. Formats structured 
JSON records partitioned cleanly by tenant and ingestion job parameters.
"""
import io
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Callable, List, Optional

from minio import Minio
from minio.error import S3Error

from src.ai.extraction.row_parsing import RowParseResult

EXTRACTION_RESULTS_BUCKET = "ceopro-extraction-results"
logger = logging.getLogger(__name__)
PreUploadCallback = Callable[[str, str, int], None]


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
        # what the source row actually said.
        "raw_fields": result.raw_fields,
        # Provenance: the exact source column header (as uploaded) behind
        # each typed_fields entry, keyed the same way - closes the
        # remaining gap in the original-file -> row/column -> normalized
        # value chain. Without this, "quantity was 1.5" is recoverable but
        # "the column named الكمية said 1.5" was not.
        "header_mapping": result.header_mapping,
        "field_confidence": result.field_confidence,
        "fallback_entities": [_entity_to_dict(e) for e in result.fallback_entities],
        "unmapped_columns": result.unmapped_columns,
    }


def build_extraction_document(
    tenant_id: str,
    ingestion_job_id: str,
    source_name: str,
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
        "source_name": source_name,
        "created_at": now,
        "row_count": len(row_results),
        "verified_field_count": verified_field_count,
        "estimated_field_count": estimated_field_count,
        "rows": rows,
    }


def _object_key(tenant_id: str, ingestion_job_id: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{tenant_id}/{ingestion_job_id}/{ts}_{uuid.uuid4().hex}.json"


def new_extraction_object_key(tenant_id: str, ingestion_job_id: str) -> str:
    """Create a tenant/job-scoped key callers can track before the remote write."""
    return _object_key(tenant_id, ingestion_job_id)


def _validate_object_key(tenant_id: str, ingestion_job_id: str, object_key: str) -> None:
    prefix = f"{tenant_id}/{ingestion_job_id}/"
    if (not object_key.startswith(prefix) or object_key == prefix
            or any(part in (".", "..") for part in object_key.split("/"))):
        raise ValueError("Extraction object key must remain within its tenant and ingestion-job prefix")


def _remove_after_failed_upload(client: Minio, bucket: str, object_key: str) -> None:
    try:
        client.remove_object(bucket, object_key)
    except S3Error as e:
        if getattr(e, "code", "") not in ("NoSuchKey", "NoSuchObject"):
            logger.exception("Could not clean up extraction object after ambiguous PUT failure (key=%s)", object_key)
    except Exception:
        logger.exception("Could not clean up extraction object after ambiguous PUT failure (key=%s)", object_key)


def _ensure_bucket(client: Minio, bucket: str) -> None:
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def object_exists(client: Minio, bucket: str, object_key: str) -> bool:
    """Return False only when MinIO confirms that this object is absent."""
    try:
        client.stat_object(bucket, object_key)
        return True
    except S3Error as e:
        if getattr(e, "code", "") in ("NoSuchKey", "NoSuchObject"):
            return False
        raise


def upload_extraction_document(
    client: Minio,
    document: dict,
    tenant_id: str,
    ingestion_job_id: str,
    bucket: str = EXTRACTION_RESULTS_BUCKET,
    *,
    object_key: Optional[str] = None,
    on_pre_upload: Optional[PreUploadCallback] = None,
) -> str:
    """
    Streams a structural JSON document into object storage under an immutable tracking path. 
    Guarantees no file clobbering or write-lock contention using unique transaction keys.
    """
    key = object_key or new_extraction_object_key(tenant_id, ingestion_job_id)
    _validate_object_key(tenant_id, ingestion_job_id, key)
    _ensure_bucket(client, bucket)
    payload = json.dumps(document, ensure_ascii=False, indent=None).encode("utf-8")
    if on_pre_upload is not None:
        on_pre_upload(bucket, key, len(payload))
    try:
        client.put_object(
            bucket_name=bucket,
            object_name=key,
            data=io.BytesIO(payload),
            length=len(payload),
            content_type="application/json",
        )
    except Exception as e:
        _remove_after_failed_upload(client, bucket, key)
        if isinstance(e, S3Error):
            raise RuntimeError(f"Failed to persist extraction document to MinIO: {e}") from e
        raise
    return key

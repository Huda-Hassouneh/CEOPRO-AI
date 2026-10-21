"""
KEEL - Extraction/ingestion endpoints (file upload, templates,
pending-record processing). See individual endpoint docstrings for the
full reasoning, preserved verbatim from main.py's original version.
"""

import io
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from src.ai import db
from src.ai.extraction.template_contract import TEMPLATE_ID
from src.ai.core.redis_client import get_redis_client
from src.ai.core.security import TenantContext, get_tenant_context
from src.ai.extraction import file_dispatch, geo_currency, ingestion_pipeline, job_management, promotion
from src.ai.extraction import minio_persistence
from src.ai.extraction import pipeline as extraction_pipeline
from src.ai.rag import pipeline as rag_pipeline
from src.ai.core.office_files import InvalidOfficeFileError
from src.ai.core import storage_ledger, usage

router = APIRouter(prefix="/extraction", tags=["extraction"])

logger = logging.getLogger("CEOPRO_AI_MAIN")

# Upload security limits (extraction/upload). No dedicated MAX_UPLOAD_SIZE_BYTES
# convention exists elsewhere in the repo yet - this is this endpoint's own,
# documented default, overridable per deployment.
_MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_SIZE_BYTES", str(10 * 1024 * 1024)))  # 10MB

# See ingestion_pipeline.process_records()'s own commit_every docstring and
# src/ai/extraction/SCALING.md for the measured cliff this avoids (a
# 51,947-row file: 8.5 hours in one transaction vs. 7 seconds of pure
# compute). 500 is a starting point (SCALING.md suggests 500-2,000), not a
# value tuned against production write latency yet.
_EXTRACTION_COMMIT_EVERY = int(os.getenv("EXTRACTION_COMMIT_EVERY", "500"))
_STORAGE_RECOVERY_GRACE = timedelta(hours=24)
_STORAGE_RECOVERY_BATCH = 100

# Content sniffing beyond the file extension - catches a trivial extension
# spoof (e.g. an arbitrary file renamed to .xlsx). CSV has no reliable magic
# bytes (it's plain text) so isn't checked here; PDF/XLSX/XLSM do.
_MAGIC_BYTES = {".pdf": b"%PDF-", ".xlsx": b"PK\x03\x04", ".xlsm": b"PK\x03\x04"}

# routers/extraction.py -> routers -> ai -> src -> repo root (one level
# deeper than main.py was, since this module now lives in routers/).
_TEMPLATES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "templates"
)


def _track_extraction_result_before_put(tenant_id: str, user_id: str, minio_client):
    """Commit the result ledger entry before upload on a tenant-scoped connection.

    Old pre-upload rows are forgotten only when MinIO confirms that the
    specific object is absent. A missing bucket or transient error is
    inconclusive and therefore leaves accounting intact.
    """
    def track(bucket: str, object_key: str, size_bytes: int) -> None:
        ledger_conn = db.app_role_connection(tenant_id, user_id)
        try:
            cutoff = datetime.now(timezone.utc) - _STORAGE_RECOVERY_GRACE
            storage_ledger.recover_stale(
                ledger_conn,
                tenant_id,
                "upload_result",
                cutoff,
                lambda stale_bucket, stale_key: minio_persistence.object_exists(
                    minio_client, stale_bucket, stale_key,
                ),
                limit=_STORAGE_RECOVERY_BATCH,
            )
            storage_ledger.record(ledger_conn, tenant_id, bucket, object_key, size_bytes, "upload_result")
            ledger_conn.commit()
        except Exception:
            ledger_conn.rollback()
            raise
        finally:
            ledger_conn.close()

    return track


def _publish_discovery_request(tenant_id: str) -> None:
    """
    The real automatic trigger closing a gap found in the production-
    hardening audit: tenant_discovery.py::discover_competitors_for_tenant()/
    discover_domain_level_competitors_for_tenant() were fully built and
    correctly wired to each other, but nothing in the live system ever
    called them - only integration tests did. "Client uploads a file ->
    products save to the DB -> the engine searches them on Social Media
    and Google" was only true in tests before this: production discovery
    was 100% a manual CLI operation.

    Fired here, right after a real upload persists new products - the
    same event-bus pattern src/market_scraper/persistence.py already
    uses for market.analysis.requested (a bare redis client .xadd(...),
    caught and logged rather than allowed to fail the request the upload
    itself already succeeded at). Consumed by src/market_scraper/
    discovery_worker.py, kept in that package (not here) for the same
    reason analysis_worker.py lives in market_scraper rather than ai/ -
    discovery is that service's own domain.

    Uses REDIS_HOST/REDIS_PORT, not REDIS_URL: this file's own
    docker-compose service (`ai`) sets those two, not REDIS_URL - see
    src/ai/forecasting/consumer.py for the same convention already
    established elsewhere in this package. core/redis_client.py's
    get_redis_client() layers optional REDIS_PASSWORD/REDIS_TLS on top,
    for any real managed Redis (unlike docker-compose's own unauthenticated
    local instance) that requires them.
    """
    try:
        get_redis_client().xadd(os.getenv("DISCOVERY_STREAM_KEY", "market.discovery.requested"), {"tenant_id": tenant_id})
    except redis.RedisError as exc:
        logger.error("could not enqueue downstream competitor discovery for tenant=%s: %s", tenant_id, exc)


@router.get("/imports")
def extraction_recent_imports(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """The tenant's own recent file imports (newest first), for Connect Data's
    "Recent Data Activity" table - RLS-scoped like every other tenant read."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        return {"imports": job_management.list_recent_imports(conn, ctx.tenant_id)}
    finally:
        conn.close()


@router.post("/process-pending")
def extraction_process_pending(limit: int = 100, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        news_count = extraction_pipeline.extract_and_store_news_records(conn, ctx.tenant_id, None, limit)
        mentions_count = extraction_pipeline.extract_and_store_social_mentions(conn, ctx.tenant_id, None, limit)
        conn.commit()
        return {"news_processed": news_count, "social_mentions_processed": mentions_count}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/templates/{fmt}")
def extraction_template(fmt: str, ctx: TenantContext = Depends(get_tenant_context)) -> FileResponse:
    """Serves the actual committed canonical template files (templates/) -
    still auth-gated (Depends(get_tenant_context)) even though the content
    itself carries no tenant data, for consistency with every other
    endpoint rather than carving out an unauthenticated exception."""
    if fmt not in ("csv", "xlsx"):
        raise HTTPException(status_code=404, detail="Unknown template format - use 'csv' or 'xlsx'.")
    path = os.path.join(_TEMPLATES_DIR, f"{TEMPLATE_ID}_v1.{fmt}")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Template file not found on this deployment.")
    # The on-disk name keeps the stable internal TEMPLATE_ID; the download
    # carries the product name.
    return FileResponse(path, filename=f"keel_sales_import_v1.{fmt}")


def _read_upload_within_limit(file: UploadFile) -> bytes:
    contents = file.file.read(_MAX_UPLOAD_BYTES + 1)
    if len(contents) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File exceeds the {_MAX_UPLOAD_BYTES}-byte upload limit.")
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    return contents


def _validate_upload_content(ext: str, contents: bytes) -> None:
    expected_magic = _MAGIC_BYTES.get(ext)
    if expected_magic and not contents.startswith(expected_magic):
        raise HTTPException(status_code=400, detail=f"File content doesn't match its '{ext}' extension.")


def _register_pdf_as_rag_document(
    conn, minio_client, tenant_id: str, user_id: Optional[str], job_id: str, file_name: str, contents: bytes,
) -> Optional[str]:
    """
    Real gap closed here, found live in a full customer-acceptance test:
    a PDF uploaded through this endpoint only ever went through the
    tabular-extraction pipeline above (file_dispatch.read_source_file()/
    process_records()) - pdfplumber.extract_tables() for a price-list-
    shaped PDF, or one page_text row per page otherwise (FALLBACK/NER
    extraction). Neither path makes the PDF's own narrative content
    (company policies, product descriptions - anything the RAG
    Assistant's "ask about your uploaded documents" promise implies)
    retrievable by the chatbot: before this, the only writer of
    rag_documents_metadata was rag/structured_summaries.py's own
    auto-generated synthetic summaries, never a real uploaded file.

    This registers the PDF the same way a human upload was always meant
    to (real object in the real ceopro-rag-knowledge bucket, a real
    rag_documents_metadata row, ingested through the exact same
    rag.pipeline.ingest_pending_documents() every other document uses -
    no parallel ingestion path) and returns its resulting processed_status
    so the caller can report it honestly rather than silently, win or
    lose. The object key is job_id-based, not filename-based - same
    "never use user input to build a storage path" rule the temp-file
    handling above already follows - and is therefore always unique per
    upload, so no collision handling is needed against the table's own
    (tenant_id, storage_bucket_path) uniqueness constraint.

    Best-effort and isolated from the main upload transaction (own
    try/except, logs and returns None on failure) for the same reason
    process_records()'s own optional MinIO upload already is: an
    unreachable/misconfigured MinIO, or a blocked embedding-model
    download, must degrade only the RAG-specific part of this upload,
    never the products/inventory/sales data this endpoint's main job
    already committed successfully above.
    """
    object_key = f"uploads/{job_id}{os.path.splitext(file_name)[1] or '.pdf'}"
    try:
        # The deterministic key lets an interrupted attempt be retried. Commit
        # its tenant-scoped byte record first so a crash around PUT cannot
        # leave a successfully stored PDF outside the storage quota.
        storage_ledger.record(conn, tenant_id, rag_pipeline.DEFAULT_BUCKET, object_key, len(contents),
                              "rag_document_upload")
        conn.commit()
        # Found in first-customer acceptance testing: nothing ever created
        # this bucket, so on a fresh MinIO every PDF failed here (NoSuchBucket)
        # and never reached the assistant. Same create-on-first-use pattern
        # minio_persistence.py and marketing/image_storage.py already use.
        if not minio_client.bucket_exists(rag_pipeline.DEFAULT_BUCKET):
            minio_client.make_bucket(rag_pipeline.DEFAULT_BUCKET)
        minio_client.put_object(
            rag_pipeline.DEFAULT_BUCKET, object_key, io.BytesIO(contents),
            length=len(contents), content_type="application/pdf",
        )
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO rag_documents_metadata
                    (tenant_id, file_name, storage_bucket_path, file_size_bytes, content_type,
                     uploaded_by_user_id, processed_status)
                VALUES (%s, %s, %s, %s, 'application/pdf', %s, 'Pending');
                """,
                (tenant_id, file_name, object_key, len(contents), user_id),
            )
            # A previous interrupted cleanup may have retained this same
            # object in the generic storage ledger. RAG metadata is now the
            # canonical byte counter for it, so do not count it twice.
        storage_ledger.forget(conn, tenant_id, rag_pipeline.DEFAULT_BUCKET, object_key)
        conn.commit()
    except Exception:
        logger.exception(
            "extraction upload: could not register PDF as a RAG document (tenant=%s job=%s)", tenant_id, job_id
        )
        conn.rollback()
        try:
            already_registered = None
            try:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT 1 FROM rag_documents_metadata WHERE tenant_id = %s AND storage_bucket_path = %s;",
                        (tenant_id, object_key),
                    )
                    already_registered = cursor.fetchone() is not None
            except Exception:
                # A failed COMMIT can be ambiguous. Count conservatively
                # unless the database proves that the metadata row exists.
                logger.exception("Could not inspect failed RAG registration (tenant=%s job=%s)", tenant_id, job_id)
                conn.rollback()
            if already_registered is True:
                storage_ledger.forget(conn, tenant_id, rag_pipeline.DEFAULT_BUCKET, object_key)
            elif already_registered is False:
                removed = storage_ledger.compensate_upload(
                    conn, tenant_id, rag_pipeline.DEFAULT_BUCKET, object_key, len(contents),
                    "rag_document_upload",
                    lambda: minio_client.remove_object(rag_pipeline.DEFAULT_BUCKET, object_key),
                )
                if not removed:
                    logger.error("Retained storage accounting for failed RAG upload cleanup (tenant=%s job=%s)",
                                 tenant_id, job_id)
            else:
                storage_ledger.record(conn, tenant_id, rag_pipeline.DEFAULT_BUCKET, object_key, len(contents),
                                      "rag_document_upload")
            conn.commit()
        except Exception:
            logger.exception("Could not reconcile failed RAG object upload (tenant=%s job=%s)", tenant_id, job_id)
            conn.rollback()
        return None

    try:
        rag_pipeline.ingest_pending_documents(conn, minio_client, tenant_id)
    except Exception:
        logger.exception(
            "extraction upload: RAG ingestion failed for just-registered document (tenant=%s job=%s)",
            tenant_id, job_id,
        )
        return "Failed"

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT processed_status FROM rag_documents_metadata WHERE tenant_id = %s AND storage_bucket_path = %s;",
            (tenant_id, object_key),
        )
        row = cursor.fetchone()
    return row[0] if row else None


def _summary_response(
    job_id: str, summary, promotion_summary: Optional[promotion.PromotionSummary] = None,
    currency_resolution: Optional[dict] = None, rag_document_status: Optional[str] = None,
) -> dict:
    response = {
        "job_id": job_id,
        "template_mode": summary.template_mode,
        "is_template_compliant": summary.is_template_compliant,
        "rows_processed": summary.rows_processed,
        "rows_partial": summary.rows_partial,
        "rows_failed": summary.rows_failed,
        "data_loss_pct": summary.data_loss_pct,
        "header_coverage_ratio": summary.header_coverage_ratio,
        "minio_object_key": summary.minio_object_key,
        "rag_document_status": rag_document_status,
        "row_outcomes": [
            {"row_index": o.row_index, "mode": o.mode, "field_errors": o.field_errors, "error": o.error}
            for o in summary.row_outcomes
        ],
    }
    if promotion_summary is not None:
        response["promotion"] = {
            "rows_promoted": promotion_summary.rows_promoted,
            "rows_skipped_incomplete": promotion_summary.rows_skipped_incomplete,
            "rows_failed": promotion_summary.rows_failed,
            "rows_duplicate": promotion_summary.rows_duplicate,
            "products_created": promotion_summary.products_created,
            "barcodes_applied": promotion_summary.barcodes_applied,
            "products_matched_by_barcode": promotion_summary.products_matched_by_barcode,
            "rows_over_product_limit": promotion_summary.rows_over_product_limit,
            "errors": promotion_summary.errors,
        }
    if currency_resolution is not None:
        # needs_confirmation=True means this currency was guessed (USD
        # fallback, no country on file) rather than derived or explicitly
        # set - surfaced here so a real caller can prompt the user to
        # confirm/correct companies.primary_currency, per spec.
        response["currency_resolution"] = currency_resolution
    return response


def _ingestion_job_completion(summary, promotion_summary) -> tuple[str, str | None]:
    """Return an existing truthful terminal state for row-level outcomes."""
    has_unresolved_rows = bool(
        summary.rows_partial or summary.rows_failed or promotion_summary.rows_skipped_incomplete
        or promotion_summary.rows_failed
    )
    if has_unresolved_rows:
        return "PARTIAL", "Some rows were not promoted and need correction or review."
    return "COMPLETED", None


@router.post("/upload")
def extraction_upload(file: UploadFile = File(...), ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """
    Uploads a file and runs it through the full ingestion pipeline
    (extraction/ingestion_pipeline.py::process_records()) - the live,
    end-to-end path for the 0%-loss/best-effort template guarantee
    (PENDING_ACTIONS.md #45/#46).

    Security, in order: auth required (same Bearer JWT as every other
    endpoint - the response carries no tenant data an unauthenticated
    caller should see, but every other endpoint requires it too, kept
    consistent); extension allowlist (file_dispatch.detect_file_type() -
    only .csv/.xlsx/.xlsm/.pdf); size-capped read (rejects an oversized
    file without buffering the whole thing into memory first); magic-byte
    content sniffing for xlsx/xlsm/pdf (catches a trivial extension
    spoof - CSV has no reliable magic bytes, skipped); the uploaded
    filename is used only as display metadata (`source_name`), never to
    construct a filesystem path - the temp file's name is generated by
    tempfile, suffixed only with the already-validated extension; the
    temp file is always removed in `finally`, success or failure.

    Known, deliberately out-of-scope-for-now gaps, flagged rather than
    silently absent: no malware/AV scanning, no request rate limiting.
    XLSM (macro-enabled Excel) is accepted - openpyxl (xlsx_adapter.py)
    never executes macro code, it only reads cell values, so this carries
    no code-execution risk from the macro content itself.

    Large files commit progress every EXTRACTION_COMMIT_EVERY rows
    (default 500, see process_records()'s own commit_every docstring and
    src/ai/extraction/SCALING.md) instead of holding the whole file in one
    transaction - a real, measured fix for a 51,947-row test file that
    took 8.5 hours in one transaction vs. 7 seconds of pure compute. A
    failure partway through this endpoint now loses at most the current
    uncommitted batch, not every row processed so far.
    """
    try:
        ext = file_dispatch.detect_file_type(file.filename or "")
    except file_dispatch.UnsupportedFileTypeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    contents = _read_upload_within_limit(file)
    _validate_upload_content(ext, contents)

    # Real lifecycle fix, on top of db_pool.py's own construction-failure
    # leak fix: a pooled Postgres connection used to be checked out HERE,
    # before writing the upload to a temp path and parsing it - neither
    # step touches Postgres at all, but for a real xlsx that parsing is
    # not instant. Holding one of only maxconn pooled connections through
    # that non-Postgres work needlessly shrinks how many requests the
    # pool can actually serve concurrently - under concurrent uploads
    # this alone can exhaust the pool even with a fully successful
    # request and zero leaks (reproduced directly in
    # test_extraction_upload_pool_lifecycle_db.py). Checkout now happens
    # only once there is real Postgres work to do.
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(contents)
            tmp_path = tmp.name
        headers, rows = file_dispatch.read_source_file(tmp_path)
    except HTTPException:
        raise
    except InvalidOfficeFileError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except UnicodeDecodeError:
        # Real gap found live in acceptance testing: a .csv saved in a
        # non-UTF-8 encoding (e.g. Windows-1252/Latin-1, a common export
        # from older POS/Excel setups - not just literally corrupt bytes)
        # used to fall through to the catch-all below and come back as a
        # generic 500 "Upload processing failed.", wrongly implying a
        # server bug for what is really an invalid/malformed upload - the
        # same class of problem the unsupported-extension and empty-file
        # checks above already report as a clean 400.
        raise HTTPException(
            status_code=400,
            detail="Could not read this file as text (tried UTF-8, UTF-16, Arabic and Western European Windows encodings). Re-save/export the CSV as UTF-8 and try again.",
        )
    except Exception:
        logger.exception("extraction upload: failed to read uploaded file (tenant=%s)", ctx.tenant_id)
        raise HTTPException(status_code=500, detail="Upload processing failed.")
    finally:
        if tmp_path is not None and os.path.exists(tmp_path):
            os.remove(tmp_path)

    # MinIO is optional here, same as ingestion_pipeline.process_records()'s
    # own minio_client=None default already documents: only "also store the
    # raw original file" needs it, nothing about parsing/creating products/
    # inventory/sales does (see that function's `if minio_client is not
    # None:` guard). A deployment without MinIO configured must not lose the
    # entire upload feature over a step it can already run without.
    try:
        minio_client = db.minio_client()
    except RuntimeError:
        minio_client = None

    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    job_id = None
    kb_reservation = None
    try:
        # Document processing allowance (plan catalog: KB per billing period,
        # ceil(bytes / 1024)); committed with the job, given back on failure.
        kb_reservation = usage.reserve(conn, ctx.tenant_id, usage.DOCUMENT_EXTRACTION, max(1, -(-len(contents) // 1024)))
        if ext == ".pdf":  # PDFs also become assistant documents (document storage allowance)
            usage.ensure_capacity(conn, ctx.tenant_id, usage.DOCUMENT_STORAGE_MB, len(contents) / 1048576)
        source_type = f"{ext.lstrip('.').upper()}_UPLOAD"
        source_id = job_management.resolve_or_create_data_source(
            conn, ctx.tenant_id, source_type, "Manual File Upload"
        )
        job_id = job_management.create_ingestion_job(conn, ctx.tenant_id, source_id, file_name=file.filename)
        conn.commit()

        summary = ingestion_pipeline.process_records(
            tenant_id=ctx.tenant_id, job_id=job_id, source_name=file.filename or f"upload{ext}",
            headers=headers, rows=rows, conn=conn, redis_client=None, minio_client=minio_client,
            commit_every=_EXTRACTION_COMMIT_EVERY,
            storage_preupload_callback=_track_extraction_result_before_put(ctx.tenant_id, ctx.user_id, minio_client)
            if minio_client is not None else None,
        )

        currency_resolution = geo_currency.resolve_company_currency(conn, ctx.tenant_id)

        promotion_summary = promotion.promote_ingested_rows(
            conn, ctx.tenant_id, job_id, summary, user_id=ctx.user_id,
            default_currency=currency_resolution["currency"],
        )

        final_status, final_error = _ingestion_job_completion(summary, promotion_summary)
        job_management.finalize_ingestion_job(
            conn, ctx.tenant_id, job_id, final_status, error=final_error,
        )
        conn.commit()

        rag_document_status = None
        if ext == ".pdf" and minio_client is not None:
            rag_document_status = _register_pdf_as_rag_document(
                conn, minio_client, ctx.tenant_id, ctx.user_id, job_id, file.filename or f"upload{ext}", contents,
            )

    except (HTTPException, usage.PlanLimitReached):
        conn.rollback()
        raise
    except Exception as e:
        logger.exception("extraction upload: ingestion pipeline failed (tenant=%s job=%s)", ctx.tenant_id, job_id)
        conn.rollback()
        if kb_reservation is not None and job_id is not None:  # committed with the job: give it back
            try:
                usage.release(conn, kb_reservation)
                conn.commit()
            except Exception:
                conn.rollback()
        if job_id is not None:
            try:
                job_management.finalize_ingestion_job(conn, ctx.tenant_id, job_id, "FAILED", error=str(e))
                conn.commit()
            except Exception:
                conn.rollback()
        raise HTTPException(status_code=500, detail="Upload processing failed.")
    finally:
        conn.close()

    # Also deliberately outside the connection's lifetime now: this is a
    # Redis call (xadd), never a Postgres one - it never needed the
    # connection held open, and previously was, for however long Redis
    # took to respond (or time out).
    if promotion_summary.products_created > 0:
        _publish_discovery_request(ctx.tenant_id)
    if getattr(promotion_summary, "rows_promoted", 0):
        _refresh_forecasts(ctx)

    return _summary_response(job_id, summary, promotion_summary, currency_resolution, rag_document_status)


def _refresh_forecasts(ctx: TenantContext) -> None:
    """New sales: bring the demand forecasts up to date in the background."""
    try:
        from src.ai.forecasting import refresh as forecast_refresh

        if forecast_refresh.auto_refresh_enabled():
            forecast_refresh.start_refresh(ctx.tenant_id, ctx.user_id)
    except Exception:
        logger.exception("Could not start the forecast refresh after an import (tenant=%s)", ctx.tenant_id)

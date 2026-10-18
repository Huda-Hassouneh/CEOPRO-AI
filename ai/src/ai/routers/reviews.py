"""
Customer reviews the business imports itself - see
market_inputs/customer_reviews.py for why this exists.
"""
import logging
import os
import tempfile

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile

from src.ai import db
from src.ai.core import tenant_cache, usage
from src.ai.core.security import TenantContext, get_tenant_context
from src.ai.extraction import file_dispatch
from src.ai.extraction.locale_config import get_tenant_locale
from src.ai.market_inputs import customer_reviews
from src.ai.routers.extraction import _read_upload_within_limit, _validate_upload_content
from src.ai.sentiment import pipeline as sentiment_pipeline
from src.ai.core.office_files import InvalidOfficeFileError

logger = logging.getLogger("CEOPRO_AI_REVIEWS")

router = APIRouter(prefix="/reviews", tags=["reviews"])

_REVIEW_FILE_TYPES = {".csv", ".xlsx", ".xlsm"}
_MAX_SENTIMENT_BATCHES = 50  # 100 reviews per batch


def _analyze_imported_reviews(tenant_id: str, user_id: str) -> None:
    """Runs after the response: classifying a few hundred reviews with the
    multilingual model takes longer than an upload request should block."""
    conn = db.app_role_connection(tenant_id, user_id)
    try:
        for _ in range(_MAX_SENTIMENT_BATCHES):
            result = sentiment_pipeline.classify_and_store_reviews(conn, tenant_id, batch_size=100)
            conn.commit()
            if not result.get("analyzed_count"):
                break
    except Exception:
        conn.rollback()
        logger.exception("sentiment analysis of imported reviews failed (tenant=%s)", tenant_id)
    finally:
        conn.close()
        tenant_cache.bump(tenant_id)


@router.post("/import")
def import_reviews_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    try:
        ext = file_dispatch.detect_file_type(file.filename or "")
    except file_dispatch.UnsupportedFileTypeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if ext not in _REVIEW_FILE_TYPES:
        raise HTTPException(status_code=400, detail="Reviews must be a CSV or Excel file.")
    contents = _read_upload_within_limit(file)
    _validate_upload_content(ext, contents)

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(contents)
            tmp_path = tmp.name
        headers, rows = file_dispatch.read_source_file(tmp_path)
    except InvalidOfficeFileError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Could not read this file as text. Re-save/export it as UTF-8 and try again.")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        # A review file counts toward the plan's monthly upload allowance,
        # in the same transaction as the import (undone if it fails).
        usage.reserve(conn, ctx.tenant_id, usage.DOCUMENT_EXTRACTION, max(1, -(-len(contents) // 1024)))
        locale = get_tenant_locale(conn, ctx.tenant_id)
        summary = customer_reviews.import_reviews(
            conn, ctx.tenant_id, headers, rows, day_first=locale.date_day_first if locale else True,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if summary.missing_columns:
        raise HTTPException(
            status_code=422,
            detail="No review-text column found. Name it e.g. 'review', 'comment', 'تعليق' or 'avis'.",
        )
    if summary.imported:
        background_tasks.add_task(_analyze_imported_reviews, ctx.tenant_id, ctx.user_id)
    return {**summary.as_dict(), "sentiment_analysis": "started" if summary.imported else "not_needed"}


@router.get("")
def list_reviews_endpoint(
    limit: int = Query(default=50, ge=1, le=200),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        reviews = customer_reviews.list_reviews(conn, ctx.tenant_id, limit=limit)
        return {"reviews": reviews}
    finally:
        conn.close()

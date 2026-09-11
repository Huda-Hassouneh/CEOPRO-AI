"""
CEOPRO AI - Service Entrypoint (PENDING_ACTIONS.md #2/#25, RED_FLAGS.md's
Critical "ceopro_admin unconditionally bypasses RLS" entry).

Before this file existed, nothing in the deployed system ever connected to
Postgres as anything other than the superuser ceopro_admin - RLS policies
were correct and regression-tested (tests/test_rls_integration_db.py) but
provided zero actual isolation, since superusers bypass RLS unconditionally
regardless of policy correctness. This is the first real request path that
connects as the restricted ceopro_app role (via db.app_role_connection())
and sets app.current_tenant_id/app.current_user_id per request.

One thin HTTP endpoint per already-built pipeline entry point (pricing/,
sentiment/, mpi/, extraction/ - the four modules this track owns per
DATA_OWNERSHIP_AND_CONTRACTS.md). forecasting/ is deliberately not
duplicated here - it already has a real trigger, forecasting/consumer.py's
Redis Streams consumer.

Auth: decodes a Bearer JWT (JWT_SECRET, HS256) for tenant_id/user_id claims.
Flagged explicitly, not silently assumed: no JWT-issuing service or claim-
shape contract exists anywhere else in this repo today - security.py only
validates an internal service-to-service token, unrelated. tenant_id/user_id
is this session's own reasonable default (matching what the RLS session
variables and .env.example's JWT_SECRET comment already imply), not a
confirmed contract with a real auth service - worth reconciling once one
exists.
"""

import logging
import os
import tempfile
from typing import Optional

import jwt
import redis
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from src.ai import db
from src.ai.extraction import file_dispatch, geo_currency, ingestion_pipeline, job_management, promotion
from src.ai.extraction import pipeline as extraction_pipeline
from src.ai.mpi import pipeline as mpi_pipeline
from src.ai.pricing import pipeline as pricing_pipeline
from src.ai.rag import llm_client as rag_llm_client
from src.ai.rag import pipeline as rag_pipeline
from src.ai.sentiment import pipeline as sentiment_pipeline

app = FastAPI(title="CEOPRO AI Service")

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
    established elsewhere in this package.
    """
    try:
        redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"), port=int(os.getenv("REDIS_PORT", "6379")),
            decode_responses=True,
        ).xadd(os.getenv("DISCOVERY_STREAM_KEY", "market.discovery.requested"), {"tenant_id": tenant_id})
    except redis.RedisError as exc:
        logging.getLogger("CEOPRO_AI_MAIN").error(
            "could not enqueue downstream competitor discovery for tenant=%s: %s", tenant_id, exc
        )

# RAG query bounds (2026-09-01 security review). /rag/query's query_text
# goes straight into a prompt sent to a paid, metered third-party API
# (Groq) - an unbounded length is a real cost/abuse vector, not just a
# correctness nicety, so this is enforced by FastAPI's own request
# validation (a 422 before the handler even runs) rather than checked
# inside the endpoint body. top_k's upper bound matches
# rag.pipeline.DEFAULT_RERANK_CANDIDATES - asking for more than the
# re-ranker's own candidate pool size can never return more results
# anyway, so capping it here is just an honest error instead of a
# silently-smaller-than-requested response.
_MAX_QUERY_TEXT_LENGTH = int(os.getenv("RAG_MAX_QUERY_TEXT_LENGTH", "2000"))

# Content sniffing beyond the file extension - catches a trivial extension
# spoof (e.g. an arbitrary file renamed to .xlsx). CSV has no reliable magic
# bytes (it's plain text) so isn't checked here; PDF/XLSX/XLSM do.
_MAGIC_BYTES = {".pdf": b"%PDF-", ".xlsx": b"PK\x03\x04", ".xlsm": b"PK\x03\x04"}

_TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "templates")


class TenantContext:
    def __init__(self, tenant_id: str, user_id: str):
        self.tenant_id = tenant_id
        self.user_id = user_id


def get_tenant_context(authorization: Optional[str] = Header(default=None)) -> TenantContext:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header.")

    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET environment variable is not set.")

    token = authorization[len("Bearer "):]
    try:
        claims = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    tenant_id = claims.get("tenant_id")
    user_id = claims.get("user_id")
    if not tenant_id or not user_id:
        raise HTTPException(status_code=401, detail="Token is missing tenant_id/user_id claims.")

    return TenantContext(tenant_id=tenant_id, user_id=user_id)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/pricing/recommend")
def pricing_recommend(product_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = pricing_pipeline.run_price_recommendation(conn, ctx.tenant_id, product_id)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.post("/sentiment/analyze-pending")
def sentiment_analyze_pending(batch_size: int = 100, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = sentiment_pipeline.classify_and_store_reviews(conn, ctx.tenant_id, batch_size)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.get("/sentiment/summary")
def sentiment_summary(
    subject_type: str,
    subject_id: Optional[str] = None,
    country_context: Optional[str] = None,
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = sentiment_pipeline.get_subject_sentiment_summary(
            conn, ctx.tenant_id, subject_type, subject_id, country_context
        )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.get("/mpi/summary")
def mpi_summary(
    subject_type: str,
    subject_id: Optional[str] = None,
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = mpi_pipeline.get_subject_mpi(conn, ctx.tenant_id, subject_type, subject_id)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.post("/rag/query")
def rag_query(
    query_text: str = Query(..., min_length=1, max_length=_MAX_QUERY_TEXT_LENGTH),
    top_k: int = Query(default=5, ge=1, le=rag_pipeline.DEFAULT_RERANK_CANDIDATES),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """
    The complete RAG chatbot call: persisted hybrid retrieval -> Cross-
    Encoder re-ranking -> context assembly -> LLM reasoning
    (rag/llm_client.py, Groq-hosted Llama - see that module's docstring for
    why). A provider/network failure (LLMError) is a 502, not a 500 - the
    retrieval half of this request genuinely succeeded, it's specifically
    the upstream LLM call that didn't, which is a meaningfully different
    failure for a caller to distinguish and retry.

    query_text/top_k are bounded (FastAPI validation, a 422 before this
    body ever runs) - see _MAX_QUERY_TEXT_LENGTH's own comment for why an
    unbounded query_text is a real cost/abuse vector against a paid
    upstream API, not just a correctness nicety.
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = rag_llm_client.answer_query(conn, ctx.tenant_id, query_text, top_k=top_k)
        conn.commit()
        return result
    except rag_llm_client.LLMError as err:
        conn.rollback()
        raise HTTPException(status_code=502, detail=str(err))
    except Exception:
        conn.rollback()
        raise HTTPException(status_code=500, detail="RAG query failed.")
    finally:
        conn.close()


@app.post("/extraction/process-pending")
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


@app.get("/extraction/templates/{fmt}")
def extraction_template(fmt: str, ctx: TenantContext = Depends(get_tenant_context)) -> FileResponse:
    """Serves the actual committed canonical template files (templates/) -
    still auth-gated (Depends(get_tenant_context)) even though the content
    itself carries no tenant data, for consistency with every other
    endpoint rather than carving out an unauthenticated exception."""
    if fmt not in ("csv", "xlsx"):
        raise HTTPException(status_code=404, detail="Unknown template format - use 'csv' or 'xlsx'.")
    path = os.path.join(_TEMPLATES_DIR, f"ceopro_sales_transaction_import_v1.{fmt}")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Template file not found on this deployment.")
    return FileResponse(path, filename=os.path.basename(path))


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


def _summary_response(
    job_id: str, summary, promotion_summary: Optional[promotion.PromotionSummary] = None,
    currency_resolution: Optional[dict] = None,
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
            "products_created": promotion_summary.products_created,
            "errors": promotion_summary.errors,
        }
    if currency_resolution is not None:
        # needs_confirmation=True means this currency was guessed (USD
        # fallback, no country on file) rather than derived or explicitly
        # set - surfaced here so a real caller can prompt the user to
        # confirm/correct companies.primary_currency, per spec.
        response["currency_resolution"] = currency_resolution
    return response


@app.post("/extraction/upload")
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

    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    tmp_path = None
    job_id = None
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(contents)
            tmp_path = tmp.name

        headers, rows = file_dispatch.read_source_file(tmp_path)

        source_type = f"{ext.lstrip('.').upper()}_UPLOAD"
        source_id = job_management.resolve_or_create_data_source(
            conn, ctx.tenant_id, source_type, "Manual File Upload"
        )
        job_id = job_management.create_ingestion_job(conn, ctx.tenant_id, source_id)
        conn.commit()

        summary = ingestion_pipeline.process_records(
            tenant_id=ctx.tenant_id, job_id=job_id, source_name=file.filename or f"upload{ext}",
            headers=headers, rows=rows, conn=conn, redis_client=None, minio_client=db.minio_client(),
            commit_every=_EXTRACTION_COMMIT_EVERY,
        )

        currency_resolution = geo_currency.resolve_company_currency(conn, ctx.tenant_id)

        promotion_summary = promotion.promote_ingested_rows(
            conn, ctx.tenant_id, job_id, summary, user_id=ctx.user_id,
            default_currency=currency_resolution["currency"],
        )

        job_management.finalize_ingestion_job(conn, ctx.tenant_id, job_id, "COMPLETED")
        conn.commit()

        if promotion_summary.products_created > 0:
            _publish_discovery_request(ctx.tenant_id)

        return _summary_response(job_id, summary, promotion_summary, currency_resolution)

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
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
        if tmp_path is not None and os.path.exists(tmp_path):
            os.remove(tmp_path)

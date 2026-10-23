"""
KEEL - POST /rag/query. See main.py's original docstring (preserved
here) for query_text/top_k/history_json bound reasoning.
"""

import json
import hashlib
import io
import logging
import math
import os
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from src.ai import db
from src.ai.billing import credits
from src.ai.core import usage
from src.ai.core.security import TenantContext, get_tenant_context
from src.ai.rag import advisor as rag_advisor
from src.ai.rag import conversation_store
from src.ai.rag import llm_client as rag_llm_client
from src.ai.rag import pipeline as rag_pipeline
from src.ai.rag import access as rag_access
from src.ai.core import storage_ledger

router = APIRouter(prefix="/rag", tags=["rag"])

logger = logging.getLogger("CEOPRO_AI_MAIN")

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

# Same reasoning as _MAX_QUERY_TEXT_LENGTH above, applied to the optional
# conversation-history payload (rag/llm_client.py::answer_query()'s new
# `history` parameter) - an unbounded JSON blob is the same cost/abuse
# vector query_text already guards against, just for a bigger field.
# llm_client._sanitize_history() separately caps the *number* of turns
# actually sent to the LLM (MAX_HISTORY_MESSAGES) - this bound is only
# about the raw request size before it ever gets that far.
_MAX_HISTORY_JSON_LENGTH = int(os.getenv("RAG_MAX_HISTORY_JSON_LENGTH", "20000"))


# An answer's claims, references and calculations, kept with the message
# so a reopened conversation shows exactly what the user saw.
_STORED_ANSWER_FIELDS = ("answer_summary", "answer_blocks", "references", "calculations", "evidence_status", "research",
                         "follow_up_questions", "answer_mode")

# Why a question got no answer, for the chat to explain it in the user's
# language: not_configured | provider_busy | provider_unavailable | internal_error.
ASSISTANT_REASON_HEADER = "X-Assistant-Reason"
ASSISTANT_SESSION_HEADER = "X-Assistant-Session-Id"


@router.post("/query")
def rag_query(
    query_text: str = Query(..., min_length=1, max_length=_MAX_QUERY_TEXT_LENGTH),
    top_k: int = Query(default=5, ge=1, le=rag_pipeline.DEFAULT_RERANK_CANDIDATES),
    history_json: Optional[str] = Query(
        default=None, max_length=_MAX_HISTORY_JSON_LENGTH,
        description=(
            'Legacy/offline path: prior turns as a JSON-encoded array of '
            '{"role", "content"} objects, oldest first. Ignored when '
            "session_id is provided - a real persisted session is now the "
            "authoritative history source (see session_id below), this stays "
            "only for a caller that never sends a session_id at all."
        ),
    ),
    session_id: Optional[str] = Query(
        default=None,
        description=(
            "A conversation_sessions.session_id from a prior call's response, or omitted to "
            "start a new persisted session. When set, prior turns are loaded from the "
            "database (not from history_json, which is ignored) and this turn's question/"
            "answer are appended to it - the same conversation now survives a page refresh "
            "or a new device, not just this one browser tab's local state."
        ),
    ),
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

    query_text/top_k/history_json are bounded (FastAPI validation, a 422
    before this body ever runs, plus an explicit 422 below for malformed
    JSON) - see _MAX_QUERY_TEXT_LENGTH/_MAX_HISTORY_JSON_LENGTH's own
    comments for why an unbounded value is a real cost/abuse vector
    against a paid upstream API, not just a correctness nicety. Individual
    malformed history *entries* inside an otherwise-valid JSON array (a
    bad role, empty content, etc.) are not rejected here - they're
    silently dropped by llm_client._sanitize_history() instead, same
    "degrade, don't break the turn" philosophy as everywhere else history
    is handled.

    session_id (new - conversation_store.py): when provided, is verified
    to belong to this exact authenticated tenant+user (RLS-enforced, not
    just an application check - see conversation_store.py's own module
    docstring) before anything else runs; an id that doesn't resolve
    (wrong tenant, wrong user, or never existed) is a 404, never silently
    treated as "start a new session" (that would let a typo/stale id
    quietly lose a user's own history rather than surfacing the error).
    """
    history = None
    if history_json and not session_id:
        try:
            history = json.loads(history_json)
        except ValueError:
            raise HTTPException(status_code=422, detail="history_json must be valid JSON.")
        if not isinstance(history, list):
            raise HTTPException(status_code=422, detail="history_json must be a JSON array.")

    usage.ensure_ai_rate(ctx.tenant_id)  # fairness: one company can't drain the shared provider
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    reservation, answered = None, False
    try:
        # Plan allowance, in tokens: an estimate is reserved atomically up
        # front and committed, so concurrent questions can't overshoot it;
        # settled to the real token count after the answer, or given back
        # below if no answer is produced, so failures never use it up.
        left = usage.remaining(conn, ctx.tenant_id, usage.RAG_ASSISTANT)
        estimate = usage.RAG_TOKEN_RESERVATION if left is None else max(1, min(usage.RAG_TOKEN_RESERVATION, left))
        reservation = usage.reserve(conn, ctx.tenant_id, usage.RAG_ASSISTANT, estimate)
        conn.commit()
        state = None
        if session_id:
            if not conversation_store.session_exists(conn, ctx.tenant_id, session_id):
                raise HTTPException(status_code=404, detail="Conversation session not found.")
            history = conversation_store.load_session_history(conn, ctx.tenant_id, session_id)
            state = conversation_store.load_session_state(conn, ctx.tenant_id, session_id)
        else:
            session_id = conversation_store.create_session(conn, ctx.tenant_id, ctx.user_id, query_text)

        conversation_store.append_message(conn, ctx.tenant_id, session_id, ctx.user_id, "user", query_text)
        # Keep the customer's question and its conversation identity even if
        # the external model is unavailable. The client can reopen this same
        # session and retry instead of seeing an error that claims the turn
        # was kept while the rollback silently discarded it.
        conn.commit()
        # Every AI call this answer makes is paid from the company's AI Credits.
        with credits.metering(ctx.tenant_id, "assistant_question", usage_class="simple_question",
                              actor_user_id=ctx.user_id):
            result = rag_advisor.answer(conn, ctx.tenant_id, query_text, top_k=top_k, history=history,
                                        user_id=ctx.user_id, state=state)
        conversation_store.append_message(
            conn, ctx.tenant_id, session_id, ctx.user_id, "assistant", result["answer"], sources=result.get("sources"),
            answer_payload={key: result.get(key) for key in _STORED_ANSWER_FIELDS},
        )
        conversation_store.save_session_state(conn, ctx.tenant_id, session_id, result.pop("state", None) or {})
        # An evidence-mode reply used no AI capacity, so it doesn't count
        # against the plan's allowance (released in `finally`).
        chargeable_answer = result.get("answer_mode") != "evidence"
        reserved_amount = reservation["amount"]
        if chargeable_answer:
            tokens = int((result.get("token_usage") or {}).get("total_tokens") or 0)
            usage.settle(conn, reservation, tokens or reservation["amount"])
        # Persist the answer and its customer allowance settlement together.
        # If settlement fails, the retained answer is rolled back as well.
        try:
            conn.commit()
        except Exception:
            reservation["amount"] = reserved_amount
            raise
        answered = chargeable_answer
        return {**result, "session_id": session_id}
    except (HTTPException, usage.PlanLimitReached, credits.BudgetError):
        conn.rollback()
        raise
    except rag_llm_client.LLMRateLimitError as err:
        # The provider's own message names its account/organisation - logged
        # for operators, never returned to the tenant.
        logger.warning("RAG query rate limited by the LLM provider (tenant=%s): %s", ctx.tenant_id, err)
        conn.rollback()
        retry_after = max(1, round(err.retry_after_seconds or 30))
        raise HTTPException(
            status_code=503,
            detail=f"The assistant is handling too many questions right now. Please try again in about {retry_after} seconds.",
            headers={"Retry-After": str(retry_after), ASSISTANT_REASON_HEADER: "provider_busy",
                     ASSISTANT_SESSION_HEADER: str(session_id)},
        )
    except rag_llm_client.LLMNotConfiguredError as err:
        # An operator problem, not a transient one: say so instead of "try again".
        logger.error("RAG query: no language model is configured: %s", err)
        conn.rollback()
        raise HTTPException(
            status_code=503,
            detail="The assistant's AI service is not set up on this server yet. An administrator needs to configure it.",
            headers={ASSISTANT_REASON_HEADER: "not_configured", ASSISTANT_SESSION_HEADER: str(session_id)},
        )
    except rag_llm_client.LLMError as err:
        logger.error("RAG query failed at the LLM provider (tenant=%s): %s", ctx.tenant_id, err)
        conn.rollback()
        raise HTTPException(
            status_code=502,
            detail="The assistant's language model is temporarily unavailable. Please try again shortly.",
            headers={ASSISTANT_REASON_HEADER: "provider_unavailable", ASSISTANT_SESSION_HEADER: str(session_id)},
        )
    except Exception:
        logger.exception("RAG query failed (tenant=%s)", ctx.tenant_id)
        conn.rollback()
        failure_headers = {ASSISTANT_REASON_HEADER: "internal_error"}
        if session_id is not None:
            failure_headers[ASSISTANT_SESSION_HEADER] = str(session_id)
        raise HTTPException(
            status_code=500, detail="RAG query failed.", headers={
                **failure_headers,
            },
        )
    finally:
        if reservation is not None and not answered:
            _give_back(conn, reservation)
        conn.close()


def _give_back(conn, reservation) -> None:
    try:
        conn.rollback()
        usage.release(conn, reservation)
        conn.commit()
    except Exception:
        logger.exception("Could not release an unused assistant reservation (tenant=%s)", reservation["tenant_id"])


UPLOADED_DOCUMENT_PREFIX = "uploads/"  # see routers/extraction.py::_register_pdf_as_rag_document
_DOCUMENT_STATUS = {"Pending": "processing", "Processed": "ready", "Failed": "failed"}


def list_uploaded_documents(conn, tenant_id: str) -> list:
    """Documents the tenant uploaded for the assistant, newest first, with
    how many searchable passages each produced. The platform's own
    auto-generated summaries (also rows in rag_documents_metadata) are
    excluded - the customer didn't upload those."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT m.document_id, m.file_name, m.file_size_bytes, m.content_type, m.uploaded_at,
                   m.processed_status, COUNT(c.chunk_id)
            FROM rag_documents_metadata m
            LEFT JOIN rag_document_chunks c ON c.tenant_id = m.tenant_id AND c.document_id = m.document_id
            WHERE m.tenant_id = %s AND m.storage_bucket_path LIKE %s
            GROUP BY m.document_id
            ORDER BY m.uploaded_at DESC;
            """,
            (tenant_id, UPLOADED_DOCUMENT_PREFIX + "%"),
        )
        rows = cursor.fetchall()
    return [
        {
            "document_id": str(document_id),
            "file_name": file_name,
            "size_bytes": int(size),
            "type": (os.path.splitext(file_name)[1].lstrip(".") or "pdf").lower(),
            "uploaded_at": uploaded_at.isoformat() if uploaded_at else None,
            "status": ("ready" if status == "Processed" and int(chunks) > 0
                       else _DOCUMENT_STATUS.get(status, "failed")),
            "chunk_count": int(chunks),
            "searchable": status == "Processed" and int(chunks) > 0,
        }
        for document_id, file_name, size, _content_type, uploaded_at, status, chunks in rows
    ]


@router.get("/documents")
def list_documents(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        if not rag_access.load_access(conn, ctx.tenant_id, ctx.user_id).allows(rag_access.DOCUMENTS):
            raise HTTPException(status_code=403, detail="Your role cannot access Knowledge Base documents.")
        return {"documents": list_uploaded_documents(conn, ctx.tenant_id)}
    finally:
        conn.close()


@router.get("/sessions")
def list_conversation_sessions(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """This tenant+user's own conversation sessions, most recently active
    first - real data for the frontend's previously-honest-but-unavailable
    listSessions()."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        sessions = conversation_store.list_sessions(conn, ctx.tenant_id, ctx.user_id)
        conn.commit()
        return {"sessions": sessions}
    finally:
        conn.close()


@router.get("/sessions/{session_id}/messages")
def get_conversation_session_messages(session_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Full message history for one session (page-refresh restore) - 404
    if session_id doesn't resolve for this tenant+user (RLS-enforced, see
    session_exists()'s own docstring)."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        if not conversation_store.session_exists(conn, ctx.tenant_id, session_id):
            raise HTTPException(status_code=404, detail="Conversation session not found.")
        messages = conversation_store.load_session_messages_for_display(conn, ctx.tenant_id, session_id)
        conn.commit()
        return {"session_id": session_id, "messages": messages}
    finally:
        conn.close()


@router.post("/documents/{document_id}/retry")
def retry_document(document_id: UUID, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Processes a document again after it failed (for example, it was
    uploaded while the search model was unavailable). Only the company's own
    uploaded documents; returns the document's new status."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    reservation = None
    reservation_committed = False
    try:
        if not rag_access.load_access(conn, ctx.tenant_id, ctx.user_id).allows(rag_access.DOCUMENTS):
            raise HTTPException(status_code=403, detail="Your role cannot access Knowledge Base documents.")
        with conn.cursor() as cursor:
            cursor.execute("SELECT file_size_bytes, processed_status FROM rag_documents_metadata WHERE tenant_id=%s AND document_id=%s AND storage_bucket_path LIKE %s;",
                           (ctx.tenant_id, str(document_id), UPLOADED_DOCUMENT_PREFIX + "%"))
            stored = cursor.fetchone()
        if stored is None:
            raise HTTPException(status_code=404, detail="Document not found.")
        if stored[1] != "Failed":
            raise HTTPException(status_code=409, detail="Only a failed document can be retried.")
        reservation = usage.reserve(conn, ctx.tenant_id, usage.DOCUMENT_EXTRACTION,
                                    max(1, math.ceil(int(stored[0]) / 1024)))
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE rag_documents_metadata SET processed_status = 'Pending'
                WHERE tenant_id = %s AND document_id = %s AND storage_bucket_path LIKE %s
                RETURNING document_id;
                """,
                (ctx.tenant_id, str(document_id), UPLOADED_DOCUMENT_PREFIX + "%"),
            )
            if cursor.fetchone() is None:
                raise HTTPException(status_code=404, detail="Document not found.")
        conn.commit()
        reservation_committed = True
        rag_pipeline.invalidate_tenant_index_cache(ctx.tenant_id)
        rag_pipeline.ingest_pending_documents(conn, db.minio_client(), ctx.tenant_id)
        document = next((d for d in list_uploaded_documents(conn, ctx.tenant_id) if d["document_id"] == str(document_id)), None)
        if not document or not document["searchable"]:
            usage.release(conn, reservation)
            conn.commit()
            reservation_committed = False
        return {"document": document}
    except HTTPException:
        conn.rollback()
        if reservation is not None and reservation_committed:
            usage.release(conn, reservation)
            conn.commit()
        raise
    except Exception:
        conn.rollback()
        if reservation is not None and reservation_committed:
            try:
                usage.release(conn, reservation)
                conn.commit()
            except Exception:
                conn.rollback()
        logger.exception("Knowledge Base retry failed (tenant=%s document=%s)", ctx.tenant_id, document_id)
        raise HTTPException(status_code=500, detail="Document processing could not be completed.")
    finally:
        conn.close()


_RAG_UPLOAD_LIMIT = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
_RAG_MAGIC = {".pdf": b"%PDF-", ".docx": b"PK\x03\x04", ".xlsx": b"PK\x03\x04"}
_RAG_CONTENT_TYPES = {".txt": "text/plain", ".md": "text/markdown", ".pdf": "application/pdf",
                      ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                      ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


@router.post("/documents/upload")
def upload_knowledge_document(file: UploadFile = File(...), ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Upload a Knowledge Base file without invoking business-data ingestion.

    The supported extensions are exactly those the existing RAG extractor can
    read. This route deliberately does not create an ingestion job or promote
    sales/products/invoices.
    """
    extension = Path(file.filename or "").suffix.lower()
    if extension not in rag_pipeline.data_access.SUPPORTED_DOCUMENT_EXTENSIONS:
        raise HTTPException(status_code=400, detail="This file type is not supported for Knowledge Base documents.")
    contents = file.file.read(_RAG_UPLOAD_LIMIT + 1)
    if len(contents) > _RAG_UPLOAD_LIMIT:
        raise HTTPException(status_code=413, detail=f"File exceeds the {_RAG_UPLOAD_LIMIT}-byte upload limit.")
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    magic = _RAG_MAGIC.get(extension)
    if magic and not contents.startswith(magic):
        raise HTTPException(status_code=400, detail=f"File content doesn't match its '{extension}' extension.")
    try:
        minio_client = db.minio_client()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Document storage is unavailable.")

    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    digest = hashlib.sha256(contents).hexdigest()
    lock_key = f"rag-document:{ctx.tenant_id}:{digest}"
    lock_acquired = False
    reservation = None
    reservation_committed = False
    object_key = f"uploads/{ctx.tenant_id}/{digest}{extension}"
    try:
        if not rag_access.load_access(conn, ctx.tenant_id, ctx.user_id).allows(rag_access.DOCUMENTS):
            raise HTTPException(status_code=403, detail="Your role cannot add Knowledge Base documents.")
        # A session lock spans DB commits and the object-store PUT, making a
        # repeated/concurrent identical upload resolve to the same document.
        with conn.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0));", (lock_key,))
            lock_acquired = True
            cursor.execute("SELECT document_id, processed_status, file_name FROM rag_documents_metadata "
                           "WHERE tenant_id=%s AND content_hash=%s ORDER BY uploaded_at DESC LIMIT 1;",
                           (ctx.tenant_id, digest))
            existing = cursor.fetchone()
        if existing:
            if existing[1] == "Pending":
                rag_pipeline.ingest_pending_documents(conn, minio_client, ctx.tenant_id)
                with conn.cursor() as cursor:
                    cursor.execute("SELECT processed_status FROM rag_documents_metadata WHERE tenant_id=%s AND document_id=%s;",
                                   (ctx.tenant_id, existing[0]))
                    latest_status = cursor.fetchone()[0]
            else:
                latest_status = existing[1]
            return {"document_id": str(existing[0]), "status": _DOCUMENT_STATUS.get(latest_status, "failed"),
                "searchable": latest_status == "Processed",
                    "duplicate": True, "file_name": existing[2]}

        size_mb = len(contents) / 1048576
        usage.ensure_capacity(conn, ctx.tenant_id, usage.DOCUMENT_STORAGE_MB, size_mb)
        reservation = usage.reserve(conn, ctx.tenant_id, usage.DOCUMENT_EXTRACTION,
                                    max(1, math.ceil(len(contents) / 1024)))
        storage_ledger.record(conn, ctx.tenant_id, rag_pipeline.DEFAULT_BUCKET, object_key, len(contents),
                              "rag_document_upload")
        file_name = Path((file.filename or f"document{extension}").replace("\\", "/")).name[:255]
        conn.commit()
        reservation_committed = True
        if not minio_client.bucket_exists(rag_pipeline.DEFAULT_BUCKET):
            minio_client.make_bucket(rag_pipeline.DEFAULT_BUCKET)
        minio_client.put_object(rag_pipeline.DEFAULT_BUCKET, object_key, io.BytesIO(contents),
                                length=len(contents), content_type=_RAG_CONTENT_TYPES[extension])
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO rag_documents_metadata "
                "(tenant_id,file_name,storage_bucket_path,file_size_bytes,content_type,uploaded_by_user_id,"
                "processed_status,content_hash) VALUES (%s,%s,%s,%s,%s,%s,'Pending',%s) RETURNING document_id;",
                (ctx.tenant_id, file_name, object_key, len(contents), _RAG_CONTENT_TYPES[extension], ctx.user_id, digest))
            document_id = str(cursor.fetchone()[0])
        storage_ledger.forget(conn, ctx.tenant_id, rag_pipeline.DEFAULT_BUCKET, object_key)
        conn.commit()
        processed = rag_pipeline.ingest_pending_documents(conn, minio_client, ctx.tenant_id)
        document = next((item for item in list_uploaded_documents(conn, ctx.tenant_id)
                         if item["document_id"] == document_id), None)
        if not document or document["status"] != "ready":
            usage.release(conn, reservation)
            conn.commit()
        return {"document_id": document_id, "status": document["status"] if document else "failed",
                "searchable": bool(document and document["status"] == "ready"), "duplicate": False,
                "processed_count": processed}
    except HTTPException:
        conn.rollback()
        raise
    except usage.PlanLimitReached as exc:
        conn.rollback()
        raise exc.as_http() from exc
    except Exception:
        logger.exception("Knowledge Base upload failed (tenant=%s)", ctx.tenant_id)
        conn.rollback()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 FROM rag_documents_metadata WHERE tenant_id=%s AND storage_bucket_path=%s;",
                               (ctx.tenant_id, object_key))
                metadata_exists = cursor.fetchone() is not None
            if metadata_exists:
                with conn.cursor() as cursor:
                    cursor.execute("UPDATE rag_documents_metadata SET processed_status='Failed' "
                                   "WHERE tenant_id=%s AND storage_bucket_path=%s;",
                                   (ctx.tenant_id, object_key))
                    storage_ledger.forget(conn, ctx.tenant_id, rag_pipeline.DEFAULT_BUCKET, object_key)
                conn.commit()
            elif minio_client.stat_object(rag_pipeline.DEFAULT_BUCKET, object_key):
                storage_ledger.compensate_upload(
                    conn, ctx.tenant_id, rag_pipeline.DEFAULT_BUCKET, object_key, len(contents),
                    "rag_document_upload",
                    lambda: minio_client.remove_object(rag_pipeline.DEFAULT_BUCKET, object_key),
                )
                conn.commit()
        except Exception:
            conn.rollback()
        if reservation is not None and reservation_committed:
            usage.release(conn, reservation)
            conn.commit()
        raise HTTPException(status_code=500, detail="Knowledge Base upload could not be completed.")
    finally:
        if lock_acquired:
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0));", (lock_key,))
                conn.commit()
            except Exception:
                conn.rollback()
        conn.close()

"""
KEEL - POST /rag/query. See main.py's original docstring (preserved
here) for query_text/top_k/history_json bound reasoning.
"""

import json
import logging
import os
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.ai import db
from src.ai.billing import credits
from src.ai.core import usage
from src.ai.core.security import TenantContext, get_tenant_context
from src.ai.rag import advisor as rag_advisor
from src.ai.rag import conversation_store
from src.ai.rag import llm_client as rag_llm_client
from src.ai.rag import pipeline as rag_pipeline

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
# That bound is for the URL (query-parameter) form only. A message sent in
# the JSON body (RagQueryBody) can be any length the server accepts for a
# request (core/body_limit.py, MAX_REQUEST_BODY_BYTES): the model only ever
# reads the parts that fit its prompt, chosen by relevance
# (rag/conversation_memory.py), so length no longer means unbounded cost.
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


class RagQueryBody(BaseModel):
    query_text: str = Field(..., min_length=1)
    session_id: Optional[str] = None


# The plan allowance running out doesn't end the chat: the question is still
# answered from the company's own evidence, with no paid AI call
# (advisor.answer(use_ai=False)). A subscription that isn't active, or a
# plan without the assistant, is still refused.
_ALLOWANCE_USED = ("QUOTA_EXHAUSTED",)
_AI_CREDITS_USED = ("BUDGET_EXHAUSTED",)


@router.post("/query")
def rag_query(
    query_text: Optional[str] = Query(default=None, min_length=1, max_length=_MAX_QUERY_TEXT_LENGTH),
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
    body: Optional[RagQueryBody] = Body(default=None),
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
    if body is not None:
        query_text, session_id = body.query_text, body.session_id or session_id
    if not query_text or not query_text.strip():
        raise HTTPException(status_code=422, detail="query_text is required.")
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
        use_ai = True
        try:
            left = usage.remaining(conn, ctx.tenant_id, usage.RAG_ASSISTANT)
            estimate = usage.RAG_TOKEN_RESERVATION if left is None else max(1, min(usage.RAG_TOKEN_RESERVATION, left))
            reservation = usage.reserve(conn, ctx.tenant_id, usage.RAG_ASSISTANT, estimate)
        except usage.PlanLimitReached as err:
            if err.reason not in _ALLOWANCE_USED:
                raise
            conn.rollback()
            use_ai = False
        conn.commit()
        state = None
        if session_id:
            if not conversation_store.session_exists(conn, ctx.tenant_id, session_id):
                raise HTTPException(status_code=404, detail="Conversation session not found.")
            # Every earlier message: the advisor sends the newest as turns and
            # recalls the rest by relevance, so nothing said is forgotten.
            history = conversation_store.load_session_history(conn, ctx.tenant_id, session_id, limit=None)
            state = conversation_store.load_session_state(conn, ctx.tenant_id, session_id)
        else:
            session_id = conversation_store.create_session(conn, ctx.tenant_id, ctx.user_id, query_text)

        conversation_store.append_message(conn, ctx.tenant_id, session_id, ctx.user_id, "user", query_text)
        # Every AI call this answer makes is paid from the company's AI Credits.
        ask = lambda use_ai: rag_advisor.answer(conn, ctx.tenant_id, query_text, top_k=top_k,  # noqa: E731
                                                history=history, user_id=ctx.user_id, state=state, use_ai=use_ai)
        try:
            with credits.metering(ctx.tenant_id, "assistant_question", usage_class="simple_question",
                                  actor_user_id=ctx.user_id):
                result = ask(use_ai)
        except credits.BudgetError as err:
            if err.reason not in _AI_CREDITS_USED:
                raise
            result = ask(False)
        conversation_store.append_message(
            conn, ctx.tenant_id, session_id, ctx.user_id, "assistant", result["answer"], sources=result.get("sources"),
            answer_payload={key: result.get(key) for key in _STORED_ANSWER_FIELDS},
        )
        conversation_store.save_session_state(conn, ctx.tenant_id, session_id, result.pop("state", None) or {})
        conn.commit()
        # An evidence-mode reply used no AI capacity, so it doesn't count
        # against the plan's allowance (released in `finally`).
        answered = result.get("answer_mode") != "evidence"
        if answered:
            tokens = int((result.get("token_usage") or {}).get("total_tokens") or 0)
            usage.settle(conn, reservation, tokens or reservation["amount"])
            conn.commit()
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
            headers={"Retry-After": str(retry_after), ASSISTANT_REASON_HEADER: "provider_busy"},
        )
    except rag_llm_client.LLMNotConfiguredError as err:
        # An operator problem, not a transient one: say so instead of "try again".
        logger.error("RAG query: no language model is configured: %s", err)
        conn.rollback()
        raise HTTPException(
            status_code=503,
            detail="The assistant's AI service is not set up on this server yet. An administrator needs to configure it.",
            headers={ASSISTANT_REASON_HEADER: "not_configured"},
        )
    except rag_llm_client.LLMError as err:
        logger.error("RAG query failed at the LLM provider (tenant=%s): %s", ctx.tenant_id, err)
        conn.rollback()
        raise HTTPException(
            status_code=502,
            detail="The assistant's language model is temporarily unavailable. Please try again shortly.",
            headers={ASSISTANT_REASON_HEADER: "provider_unavailable"},
        )
    except Exception:
        logger.exception("RAG query failed (tenant=%s)", ctx.tenant_id)
        conn.rollback()
        raise HTTPException(
            status_code=500, detail="RAG query failed.", headers={ASSISTANT_REASON_HEADER: "internal_error"},
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
            "status": _DOCUMENT_STATUS.get(status, "failed"),
            "chunk_count": int(chunks),
        }
        for document_id, file_name, size, _content_type, uploaded_at, status, chunks in rows
    ]


@router.get("/documents")
def list_documents(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
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
    try:
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
        rag_pipeline.ingest_pending_documents(conn, db.minio_client(), ctx.tenant_id)
        document = next((d for d in list_uploaded_documents(conn, ctx.tenant_id) if d["document_id"] == str(document_id)), None)
        return {"document": document}
    except HTTPException:
        conn.rollback()
        raise
    finally:
        conn.close()

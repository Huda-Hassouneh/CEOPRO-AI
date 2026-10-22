"""
KEEL - RAG Ingestion + Retrieval Pipeline (spec S21 groundwork).

Chunks and their embeddings are persisted to rag_document_chunks (audit
finding P1 - the table and its pgvector `embedding` column already existed,
migration 20260827000100_add_rag_embedding_column.sql, unused until now).
Ingestion (this module, at upload/reprocessing time) is the only place that
touches MinIO or the embedding model; retrieval reads the already-embedded
chunks straight out of Postgres. That's the entire fix: what used to be
"re-fetch, re-chunk, re-embed the whole corpus on every question asked" is
now "pay that cost once, per document, when it's ingested."

Efficiency follow-up (2026-09-01 review): persistence alone still left
build_hybrid_index() re-tokenizing the entire tenant corpus for BM25 and
re-building the FAISS index from scratch on every single retrieval call -
cheaper than re-embedding, but still real, repeated, avoidable CPU work for
a corpus that hasn't changed since the last query. _TENANT_INDEX_CACHE
holds one built TenantIndex per tenant, in this process's memory, reused
across calls until ingest_pending_documents() invalidates it (the only
thing that changes a tenant's chunks). Deliberately in-process, not Redis/
shared - same reasoning bm25_index.py already gives for keeping BM25 state
in memory rather than treating it as a system of record: the persisted
rows in Postgres are the source of truth, this cache is disposable and
rebuilds correctly (just slower) on a cold process or a cache miss. In a
multi-worker deployment each worker holds its own cache - acceptable here
since a stale cache only ever causes a slightly-out-of-date answer for one
worker's queries until its own next ingestion-triggered invalidation or
restart, never wrong data across tenants (still keyed strictly by
tenant_id).

This module implements retrieval only (lexical + semantic + fusion +
re-ranking + context assembly) - not the "LLM REASONING" step of spec S21's
RAG workflow. That is deliberately abstracted away entirely: run_retrieval()
returns an AssembledContext (retrieval_types.py) - context text plus source
chunk citations - ready to hand to whatever LLM provider/model gets chosen
(out of scope here; see AI_PROGRESS.md/PENDING_ACTIONS.md). This module has
no knowledge of, dependency on, or reference to any LLM API.
"""

import logging
import os
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

from src.ai.rag import data_access
from src.ai.rag import embeddings as embeddings_module
from src.ai.rag.bm25_index import BM25Index
from src.ai.rag.chunking import chunk_pages, chunk_text
from src.ai.rag.embeddings import embed, try_embed
from src.ai.rag.faiss_index import FAISSIndex
from src.ai.rag.hybrid_retrieval import reciprocal_rank_fusion
from src.ai.rag.reranking import rerank
from src.ai.rag.retrieval_types import AssembledContext, ScoredChunk

logger = logging.getLogger("CEOPRO_AI_RAG_PIPELINE")

DEFAULT_BUCKET = "ceopro-rag-knowledge"

# How many RRF-fused candidates feed the re-ranker before it narrows to the
# caller's real top_k (audit finding P2, and what makes P7's re-ranker
# meaningful at all - re-ranking a pool that was already starved to top_k
# before fusion can't recover ranking quality RRF never had a chance to
# produce). Not spec-mandated, a reasonable "wide enough to matter, narrow
# enough to keep re-ranking cost bounded" default.
DEFAULT_RERANK_CANDIDATES = 20

# The cross-encoder re-ranker runs on torch (~1.8 GB resident with the torch
# embedder, measured by scripts/rag_runtime_check.py). On a host too small for
# it, RAG_RERANKER_ENABLED=false keeps the RRF-fused order - the same
# fallback a re-ranker failure already uses - without trying to load it.
RERANKER_ENABLED = os.getenv("RAG_RERANKER_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")

# See run_retrieval()'s own docstring for why this has no built-in numeric
# default - unset (None) unless an operator has actually calibrated one
# against their real reranker's score distribution and set
# RAG_MIN_CONFIDENCE_SCORE themselves.
_MIN_CONFIDENCE_SCORE_ENV = os.getenv("RAG_MIN_CONFIDENCE_SCORE")
DEFAULT_MIN_CONFIDENCE_SCORE: Optional[float] = (
    float(_MIN_CONFIDENCE_SCORE_ENV) if _MIN_CONFIDENCE_SCORE_ENV else None
)


@dataclass
class TenantIndex:
    bm25: BM25Index
    faiss: FAISSIndex


# See this module's docstring for what this cache is and isn't. A plain
# dict + lock, not a library, for the same reason BM25Index/FAISSIndex
# themselves are plain in-memory objects - this is per-process disposable
# state, not shared infrastructure.
_TENANT_INDEX_CACHE: Dict[str, TenantIndex] = {}
_TENANT_INDEX_CACHE_LOCK = threading.Lock()


def invalidate_tenant_index_cache(tenant_id: str) -> None:
    """Drops the cached index for one tenant, if any. Called automatically by
    ingest_pending_documents() whenever it actually changes that tenant's
    chunks - exposed here too for a caller that mutates rag_document_chunks
    some other way (a bulk admin re-ingest script, for instance)."""
    with _TENANT_INDEX_CACHE_LOCK:
        _TENANT_INDEX_CACHE.pop(tenant_id, None)


def ingest_pending_documents(conn, minio_client, tenant_id: str, bucket: str = DEFAULT_BUCKET) -> int:
    """
    Marks every 'Pending' document as 'Processed' once its text is
    successfully fetched, chunked, embedded, and persisted, or 'Failed' if
    any of that fails - spec S12: "The system must never silently discard
    invalid data." Returns the count of documents successfully processed.

    Persists via data_access.replace_document_chunks() - a delete-then-
    insert that is safe to run again for the same document_id (a retry
    after a partial failure, or a genuine re-ingestion once whatever
    upload path exists flips a re-uploaded document back to 'Pending' -
    see replace_document_chunks()'s own docstring for the boundary of what
    this module does and doesn't own of that lifecycle).
    """
    # Session-level lock survives the per-document commits below. A worker
    # crash releases it automatically; another worker can then resume the
    # remaining Pending documents without concurrent duplicate chunk writes.
    lock_key = f"rag-ingest:{tenant_id}"
    with conn.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0));", (lock_key,))
    try:
        return _ingest_pending_documents_locked(conn, minio_client, tenant_id, bucket)
    finally:
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0));", (lock_key,))
            conn.commit()
        except Exception:
            conn.rollback()


def _ingest_pending_documents_locked(conn, minio_client, tenant_id: str, bucket: str) -> int:
    pending = data_access.list_documents(conn, tenant_id, status="Pending")
    processed_count = 0

    for doc in pending:
        try:
            text = data_access.fetch_document_text(minio_client, bucket, doc["storage_bucket_path"])
            chunks = chunk_text(text)
            if not chunks:
                raise ValueError("document produced no chunks (empty or whitespace-only content)")

            # Without the semantic model the document is still stored and
            # searchable by keyword; its vectors are filled in later by
            # backfill_missing_embeddings() once the model is available.
            doc_embeddings = try_embed(chunks)
            data_access.replace_document_chunks(
                conn, tenant_id, doc["document_id"], chunks, doc_embeddings,
                embeddings_module.MODEL_NAME if doc_embeddings is not None else None,
                pages=chunk_pages(text, len(chunks)),
            )
            data_access.mark_document_status(conn, doc["document_id"], "Processed")
            conn.commit()  # per document: one bad file must not roll back or poison the rest
            processed_count += 1
        except Exception as err:
            # Do not copy document names, extracted text, parser details, or
            # object keys into application logs. The tenant-visible status
            # records failure; operators only need a safe exception class.
            logger.error("Failed to ingest RAG document id=%s tenant=%s error_type=%s",
                         doc["document_id"], tenant_id, type(err).__name__)
            # A DB error mid-insert leaves the transaction aborted, which would make
            # the status update below (and every later document) fail too.
            conn.rollback()
            data_access.mark_document_status(conn, doc["document_id"], "Failed")
            conn.commit()

    backfilled = backfill_missing_embeddings(conn, tenant_id)
    if processed_count > 0 or backfilled:
        invalidate_tenant_index_cache(tenant_id)
    logger.info(f"Ingestion complete for tenant={tenant_id}: {processed_count}/{len(pending)} processed")
    return processed_count


def backfill_missing_embeddings(conn, tenant_id: str, batch_size: int = 256, max_batches: int = 40) -> int:
    """Embeds chunks stored while the semantic model was unavailable, and
    re-embeds chunks whose vector came from another model (after a model
    change). Returns how many were filled in (0 when none are missing or the
    model is still unavailable)."""
    filled = 0
    for _ in range(max_batches):
        missing = data_access.load_chunks_missing_embeddings(conn, tenant_id, limit=batch_size,
                                                             model_version=embeddings_module.MODEL_NAME)
        if not missing:
            break
        vectors = try_embed([text for _, text in missing])
        if vectors is None:
            break
        data_access.set_chunk_embeddings(
            conn, tenant_id, [chunk_id for chunk_id, _ in missing], vectors, embeddings_module.MODEL_NAME
        )
        conn.commit()
        filled += len(missing)
    return filled


def build_tenant_index(conn, tenant_id: str) -> BM25Index:
    """Lexical-only index (no embedding model needed), built from persisted chunks - no MinIO fetch."""
    rows = data_access.load_tenant_chunks(conn, tenant_id)
    chunks = [(chunk_id, text) for chunk_id, text, _ in rows]
    return BM25Index(chunks)


def build_hybrid_index(conn, tenant_id: str, use_cache: bool = True) -> TenantIndex:
    """
    Builds both the lexical (BM25) and semantic (FAISS) indexes from
    persisted chunks - no MinIO fetch, no re-embedding; embeddings were
    computed once at ingest time (ingest_pending_documents()).

    use_cache=True (the default, and what run_retrieval() uses): reuses a
    per-process cached TenantIndex for this tenant when one exists, instead
    of re-tokenizing the whole corpus for BM25 and rebuilding the FAISS
    index from scratch on every call - see this module's own docstring for
    what the cache is/isn't and how it's invalidated. Pass False to force a
    fresh build (tests, or a caller that must see the latest chunks
    regardless of cache state).
    """
    if use_cache:
        with _TENANT_INDEX_CACHE_LOCK:
            cached = _TENANT_INDEX_CACHE.get(tenant_id)
        if cached is not None:
            return cached

    rows = data_access.load_tenant_chunks(conn, tenant_id, model_version=embeddings_module.MODEL_NAME)
    if any(embedding is None for _, _, embedding in rows) and embeddings_module.BACKEND not in embeddings_module.DISABLED_BACKENDS:
        # Chunks without a vector from the current model (stored while it was
        # unavailable, or before a model change): embed them now, so the
        # first question after a change searches every document by meaning.
        try:
            if backfill_missing_embeddings(conn, tenant_id):
                rows = data_access.load_tenant_chunks(conn, tenant_id, model_version=embeddings_module.MODEL_NAME)
        except Exception as err:  # noqa: BLE001 - keyword search still covers them
            conn.rollback()
            logger.warning(f"tenant={tenant_id}: re-embedding stored chunks failed: {err}")
    chunks = [(chunk_id, text) for chunk_id, text, _ in rows]
    # Keyword search covers every chunk; semantic search covers the chunks
    # that have vectors (all of them, unless some were stored while the
    # embedding model was unavailable).
    embedded = [(chunk_id, text, embedding) for chunk_id, text, embedding in rows if embedding is not None]
    # A different dimension (embedding model swapped, old rows not yet re-embedded)
    # would crash np.stack and take down every query for the tenant.
    if embedded:
        dim = embedded[0][2].shape[0]
        mismatched = [row for row in embedded if row[2].shape[0] != dim]
        if mismatched:
            logger.warning(
                f"tenant={tenant_id}: {len(mismatched)} chunks have an embedding dimension != {dim}; "
                f"semantic search skips them - re-embed to fix"
            )
            embedded = [row for row in embedded if row[2].shape[0] == dim]
    embeddings = (
        np.stack([embedding for _, _, embedding in embedded]).astype(np.float32)
        if embedded else np.empty((0, 0), dtype=np.float32)
    )
    index = TenantIndex(
        bm25=BM25Index(chunks),
        faiss=FAISSIndex([(chunk_id, text) for chunk_id, text, _ in embedded], embeddings),
    )

    if use_cache:
        with _TENANT_INDEX_CACHE_LOCK:
            _TENANT_INDEX_CACHE[tenant_id] = index

    return index


def retrieve(index: BM25Index, query_text: str, top_k: int = 5) -> List[ScoredChunk]:
    return index.query(query_text, top_k=top_k)


def retrieve_hybrid(
    tenant_index: TenantIndex, query_text: str, top_k: int = 5, candidate_pool_size: int = None
) -> List[ScoredChunk]:
    """
    Result fusion per spec S21's RAG workflow: STRUCTURED QUERY + BM25 +
    FAISS -> RESULT FUSION.

    Audit finding P2: each retriever now contributes `candidate_pool_size`
    candidates to fusion, not just `top_k` - previously both retrievers
    were capped at the same top_k as the final output, which meant a chunk
    ranked, say, 6th by BM25 could never reach RRF at all even if FAISS
    ranked it #1, artificially capping recall. Fusion still narrows to
    `top_k` at the end; only the pre-fusion pool widened. Default pool
    size (max(top_k * 4, 20)) is a standard "retrieve wide, fuse narrow"
    ratio, not tuned against this corpus specifically.
    """
    candidate_pool_size = candidate_pool_size or max(top_k * 4, 20)
    bm25_results = tenant_index.bm25.query(query_text, top_k=candidate_pool_size)
    # No documents with vectors -> nothing for semantic search to find, so
    # the model isn't loaded at all; model unavailable -> keyword only.
    if len(tenant_index.faiss) == 0:
        return bm25_results[:top_k]
    query_vectors = try_embed([query_text])
    if query_vectors is None:
        return bm25_results[:top_k]
    faiss_results = tenant_index.faiss.query(query_vectors[0], top_k=candidate_pool_size)
    return reciprocal_rank_fusion(bm25_results, faiss_results, top_k=top_k)


def assemble_context(query_text: str, chunks: List[ScoredChunk]) -> AssembledContext:
    """
    Spec S21's "CONTEXT ASSEMBLY" stage: turns a ranked chunk list into the
    text an LLM prompt would actually include, plus a parallel `sources`
    list so whatever consumes this can cite which chunk backed which part
    of an answer. Deliberately not opinionated about prompt templating
    beyond a plain, source-labeled concatenation - the LLM layer this
    calls into (out of scope here) owns its own prompt format.
    """
    if not chunks:
        return AssembledContext(query=query_text, context_text="", sources=[])

    sections = []
    sources = []
    for i, chunk in enumerate(chunks, start=1):
        sections.append(f"[Source {i}]\n{chunk.text}")
        sources.append({"source_index": i, "chunk_id": chunk.chunk_id, "score": chunk.score})

    return AssembledContext(query=query_text, context_text="\n\n".join(sections), sources=sources)


def run_retrieval(
    conn,
    tenant_id: str,
    query_text: str,
    top_k: int = 5,
    rerank_candidates: int = DEFAULT_RERANK_CANDIDATES,
    use_reranker: bool = True,
    min_confidence_score: Optional[float] = DEFAULT_MIN_CONFIDENCE_SCORE,
) -> AssembledContext:
    """
    The complete pipeline up to (not including) LLM reasoning: load the
    persisted hybrid index -> RRF fusion over a wide candidate pool ->
    Cross-Encoder re-ranking -> context assembly. This is the one function
    a future LLM-integration caller needs.

    Production-grade reliability: a re-ranker failure (model download
    issue, out-of-memory, etc.) does not fail the whole request - it falls
    back to the RRF-fused order, truncated to top_k, and logs the error.
    Retrieval degrading to "slightly less precisely ranked" is an
    acceptable failure mode; retrieval failing outright over a re-ranking
    problem is not, given nothing else in this pipeline treats a
    lower-priority stage's failure as fatal to the whole call (see
    ingest_pending_documents()'s per-document error handling for the same
    philosophy applied elsewhere in this module).

    Grounding / anti-hallucination (2026-09-01 review): min_confidence_score,
    when set, drops any ranked chunk scoring below it before context
    assembly - if that empties the result entirely, the caller
    (llm_client.answer_query()) still calls the LLM (with empty
    context_text), but SYSTEM_PROMPT itself instructs it to say so
    explicitly rather than guess, in the user's own language, so a corpus
    that plainly didn't match still gets a real, correctly-localized
    decline instead of guessed content. Deliberately
    NOT given a default value: Cross-Encoder score ranges are model- and
    corpus-specific (this deployment's reranker was never calibrated
    against a labeled relevance dataset), so a made-up "safe-looking"
    threshold could reject good matches exactly as easily as bad ones.
    Enable it (env RAG_MIN_CONFIDENCE_SCORE, or pass it directly) only
    after observing this reranker's real score distribution on your own
    corpus and queries.
    """
    tenant_index = build_hybrid_index(conn, tenant_id)
    fused = retrieve_hybrid(tenant_index, query_text, top_k=rerank_candidates)

    if use_reranker and RERANKER_ENABLED and fused:
        try:
            ranked = rerank(query_text, fused, top_k=top_k)
        except Exception as err:
            logger.error(f"Re-ranking failed for tenant={tenant_id}, falling back to RRF order: {err}")
            ranked = fused[:top_k]
    else:
        ranked = fused[:top_k]

    ranked = apply_confidence_filter(ranked, min_confidence_score)

    return assemble_context(query_text, ranked)


def apply_confidence_filter(
    chunks: List[ScoredChunk], min_confidence_score: Optional[float]
) -> List[ScoredChunk]:
    """
    Pure filter, split out from run_retrieval() so it's unit-testable
    without a live database: drops any chunk scoring below
    min_confidence_score, or returns `chunks` unchanged when it's None
    (the default - see run_retrieval()'s own docstring for why no numeric
    default is set here).
    """
    if min_confidence_score is None:
        return chunks
    return [chunk for chunk in chunks if chunk.score >= min_confidence_score]

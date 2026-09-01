"""
CEOPRO AI - RAG Ingestion + Retrieval Pipeline (spec S21 groundwork).

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
from src.ai.rag.chunking import chunk_text
from src.ai.rag.embeddings import embed
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
    pending = data_access.list_documents(conn, tenant_id, status="Pending")
    processed_count = 0

    for doc in pending:
        try:
            text = data_access.fetch_document_text(minio_client, bucket, doc["storage_bucket_path"])
            chunks = chunk_text(text)
            if not chunks:
                raise ValueError("document produced no chunks (empty or whitespace-only content)")

            doc_embeddings = embed(chunks)
            data_access.replace_document_chunks(
                conn, tenant_id, doc["document_id"], chunks, doc_embeddings, embeddings_module.MODEL_NAME
            )
            data_access.mark_document_status(conn, doc["document_id"], "Processed")
            processed_count += 1
        except Exception as err:
            logger.error(f"Failed to ingest document={doc['document_id']} file={doc['file_name']}: {err}")
            data_access.mark_document_status(conn, doc["document_id"], "Failed")

    conn.commit()
    if processed_count > 0:
        invalidate_tenant_index_cache(tenant_id)
    logger.info(f"Ingestion complete for tenant={tenant_id}: {processed_count}/{len(pending)} processed")
    return processed_count


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

    rows = data_access.load_tenant_chunks(conn, tenant_id)
    chunks = [(chunk_id, text) for chunk_id, text, _ in rows]
    embeddings = np.stack([embedding for _, _, embedding in rows]).astype(np.float32) if rows else np.empty((0, 0), dtype=np.float32)
    index = TenantIndex(bm25=BM25Index(chunks), faiss=FAISSIndex(chunks, embeddings))

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
    query_embedding = embed([query_text])[0]
    faiss_results = tenant_index.faiss.query(query_embedding, top_k=candidate_pool_size)
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
    (llm_client.answer_query()) already short-circuits on empty
    context_text into "I don't have any relevant information", never
    calling the LLM on a corpus that plainly didn't match. Deliberately
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

    if use_reranker and fused:
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

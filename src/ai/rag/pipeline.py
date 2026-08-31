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

This module implements retrieval only (lexical + semantic + fusion +
re-ranking + context assembly) - not the "LLM REASONING" step of spec S21's
RAG workflow. That is deliberately abstracted away entirely: run_retrieval()
returns an AssembledContext (retrieval_types.py) - context text plus source
chunk citations - ready to hand to whatever LLM provider/model gets chosen
(out of scope here; see AI_PROGRESS.md/PENDING_ACTIONS.md). This module has
no knowledge of, dependency on, or reference to any LLM API.
"""

import logging
from dataclasses import dataclass
from typing import List

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


@dataclass
class TenantIndex:
    bm25: BM25Index
    faiss: FAISSIndex


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
    logger.info(f"Ingestion complete for tenant={tenant_id}: {processed_count}/{len(pending)} processed")
    return processed_count


def build_tenant_index(conn, tenant_id: str) -> BM25Index:
    """Lexical-only index (no embedding model needed), built from persisted chunks - no MinIO fetch."""
    rows = data_access.load_tenant_chunks(conn, tenant_id)
    chunks = [(chunk_id, text) for chunk_id, text, _ in rows]
    return BM25Index(chunks)


def build_hybrid_index(conn, tenant_id: str) -> TenantIndex:
    """Builds both the lexical (BM25) and semantic (FAISS) indexes from persisted chunks - no MinIO fetch,
    no re-embedding; embeddings were computed once at ingest time (ingest_pending_documents())."""
    rows = data_access.load_tenant_chunks(conn, tenant_id)
    chunks = [(chunk_id, text) for chunk_id, text, _ in rows]
    embeddings = np.stack([embedding for _, _, embedding in rows]).astype(np.float32) if rows else np.empty((0, 0), dtype=np.float32)
    return TenantIndex(bm25=BM25Index(chunks), faiss=FAISSIndex(chunks, embeddings))


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

    return assemble_context(query_text, ranked)

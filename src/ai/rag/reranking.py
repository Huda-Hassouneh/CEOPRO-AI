"""
CEOPRO AI - Cross-Encoder Re-ranking (spec S21's "OPTIONAL RERANKING" stage,
audit finding P7).

A cross-encoder jointly encodes (query, candidate) pairs instead of
comparing independently-computed embeddings - meaningfully higher
precision than the bi-encoder FAISS retriever alone, at meaningfully
higher cost (one forward pass per candidate, not one pass total). This is
only viable bounded to a small candidate pool (see
hybrid_retrieval.reciprocal_rank_fusion's own top_k / candidate_pool_size
- pipeline.run_retrieval() widens the RRF output specifically so this
stage has more than the final top_k to actually rerank).

Model choice: multilingual, not the more commonly reached-for English-only
cross-encoder/ms-marco-MiniLM-L-6-v2 - this platform has an explicit
Arabic-English code-switching requirement (spec S8) that the rest of this
retrieval stack already honors (embeddings.py's multilingual model,
bm25_index.py's Unicode-aware tokenizer); a reranker that silently
degrades on Arabic input would undo that.
"""

import os
from typing import Callable, List, Optional

from src.ai.rag.retrieval_types import ScoredChunk

DEFAULT_MODEL_NAME = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
MODEL_NAME = os.getenv("RAG_RERANKER_MODEL", DEFAULT_MODEL_NAME)

_model_cache = {}


def get_model(model_name: str = None):
    """
    Lazily loads and caches the cross-encoder - same reasoning and pattern
    as embeddings.py's get_model(): downloading/loading on every call would
    defeat the point, and caching by name lets tests override
    RAG_RERANKER_MODEL without cross-contaminating a differently-configured
    caller in the same process. Imports sentence_transformers.CrossEncoder
    lazily (not at module import time) so pure offline tests that inject
    their own scorer (see rerank()'s `model` param) never need the real
    dependency's heavier import path to be exercised.
    """
    model_name = model_name or MODEL_NAME
    if model_name not in _model_cache:
        from sentence_transformers import CrossEncoder
        _model_cache[model_name] = CrossEncoder(model_name)
    return _model_cache[model_name]


def rerank(
    query: str, candidates: List[ScoredChunk], top_k: int = 5, model=None, predict_fn: Optional[Callable] = None
) -> List[ScoredChunk]:
    """
    Re-scores `candidates` (typically a wider RRF-fused pool, not just the
    final top_k - see pipeline.run_retrieval()) by joint (query, candidate)
    relevance, returns the top_k by that score.

    `model`/`predict_fn` exist purely for dependency injection (unit tests
    inject a fake scorer instead of downloading a real ~470MB model; a real
    caller passes neither and gets get_model()'s cached CrossEncoder).
    predict_fn, if given, must behave like CrossEncoder.predict(pairs) ->
    Iterable[float].

    Empty `candidates` returns [] without loading any model - avoids
    paying model-load cost on a query that already produced nothing to
    rerank (e.g. an empty tenant corpus).
    """
    if not candidates:
        return []

    if predict_fn is None:
        model = model or get_model()
        predict_fn = model.predict

    pairs = [(query, candidate.text) for candidate in candidates]
    scores = predict_fn(pairs)

    reranked = sorted(zip(candidates, scores), key=lambda pair: pair[1], reverse=True)
    return [
        ScoredChunk(chunk_id=candidate.chunk_id, text=candidate.text, score=float(score))
        for candidate, score in reranked[:top_k]
    ]

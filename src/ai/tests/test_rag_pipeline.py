"""
Offline tests for pipeline.py's pure functions - assemble_context() and
apply_confidence_filter() have no I/O and never had unit coverage before
(only exercised indirectly through test_rag_integration.py's live-DB
tests). DB/MinIO/model-touching paths (ingest_pending_documents,
build_tenant_index, build_hybrid_index, run_retrieval) are covered there
instead, per this module's existing split.
"""

from src.ai.rag.pipeline import apply_confidence_filter, assemble_context
from src.ai.rag.retrieval_types import ScoredChunk


def sc(chunk_id, text, score):
    return ScoredChunk(chunk_id=chunk_id, text=text, score=score)


def test_empty_chunks_produces_empty_context_not_an_error():
    context = assemble_context("some query", [])
    assert context.query == "some query"
    assert context.context_text == ""
    assert context.sources == []


def test_context_text_labels_each_source_and_preserves_rank_order():
    chunks = [sc("c1", "first chunk text", 0.9), sc("c2", "second chunk text", 0.5)]
    context = assemble_context("q", chunks)

    assert "[Source 1]\nfirst chunk text" in context.context_text
    assert "[Source 2]\nsecond chunk text" in context.context_text
    assert context.context_text.index("first chunk text") < context.context_text.index("second chunk text")


def test_sources_list_carries_chunk_id_and_score_for_citation():
    chunks = [sc("chunk-abc", "text", 0.75)]
    context = assemble_context("q", chunks)

    assert context.sources == [{"source_index": 1, "chunk_id": "chunk-abc", "score": 0.75}]


def test_confidence_filter_returns_chunks_unchanged_when_threshold_is_none():
    """The default (unset) behavior - see run_retrieval()'s own docstring
    for why no numeric threshold is set by default."""
    chunks = [sc("c1", "text", 0.1), sc("c2", "text", 0.9)]
    assert apply_confidence_filter(chunks, None) == chunks


def test_confidence_filter_drops_chunks_below_the_threshold():
    chunks = [sc("low", "text", 0.1), sc("high", "text", 0.9)]
    result = apply_confidence_filter(chunks, min_confidence_score=0.5)
    assert [c.chunk_id for c in result] == ["high"]


def test_confidence_filter_keeps_a_chunk_exactly_at_the_threshold():
    chunks = [sc("exact", "text", 0.5)]
    result = apply_confidence_filter(chunks, min_confidence_score=0.5)
    assert [c.chunk_id for c in result] == ["exact"]


def test_confidence_filter_can_empty_the_result_entirely():
    """The case that matters for grounding: nothing scored well enough,
    so the caller (llm_client.answer_query()) sees empty context_text and
    never calls the LLM - proven end-to-end in test_rag_integration.py."""
    chunks = [sc("c1", "text", 0.1), sc("c2", "text", 0.2)]
    assert apply_confidence_filter(chunks, min_confidence_score=0.9) == []

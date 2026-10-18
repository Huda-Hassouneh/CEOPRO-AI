"""
Tests reranking.py's sorting/truncation logic with an injected fake scorer
(predict_fn) - doesn't need the real Cross-Encoder model (that's covered
separately, gated behind AI_TEST_RERANKING since it needs a real model
download on first use, same convention as test_rag_embeddings.py).
"""

from src.ai.rag.reranking import rerank
from src.ai.rag.retrieval_types import ScoredChunk


def sc(chunk_id, text, score=0.0):
    return ScoredChunk(chunk_id=chunk_id, text=text, score=score)


def test_empty_candidates_returns_empty_without_calling_the_model():
    calls = []
    result = rerank("query", [], top_k=5, predict_fn=lambda pairs: calls.append(pairs) or [])
    assert result == []
    assert calls == []  # never invoked - no model-load cost paid for nothing to rerank


def test_reorders_candidates_by_predicted_score_not_input_order():
    candidates = [sc("a", "low relevance"), sc("b", "high relevance"), sc("c", "medium relevance")]

    def fake_predict(pairs):
        # cross-encoders score (query, text) pairs; fake scores keyed by text content
        return [{"low relevance": 0.1, "high relevance": 0.9, "medium relevance": 0.5}[text] for _, text in pairs]

    result = rerank("relevance query", candidates, top_k=3, predict_fn=fake_predict)

    assert [r.chunk_id for r in result] == ["b", "c", "a"]
    assert result[0].score == 0.9


def test_top_k_truncates_the_reranked_list():
    candidates = [sc(f"c{i}", f"text {i}") for i in range(10)]
    result = rerank("query", candidates, top_k=3, predict_fn=lambda pairs: list(range(len(pairs))))
    assert len(result) == 3


def test_predict_fn_receives_query_paired_with_each_candidate_text():
    candidates = [sc("a", "first"), sc("b", "second")]
    received = {}

    def fake_predict(pairs):
        received["pairs"] = pairs
        return [0.0] * len(pairs)

    rerank("my query", candidates, top_k=2, predict_fn=fake_predict)
    assert received["pairs"] == [("my query", "first"), ("my query", "second")]


def test_get_model_is_not_invoked_when_predict_fn_is_supplied():
    """Regression guard: passing predict_fn must bypass get_model()/CrossEncoder
    entirely, not just override its result - otherwise every offline test in
    this file would silently require the real dependency and a network call."""
    import src.ai.rag.reranking as reranking_module

    original_get_model = reranking_module.get_model
    reranking_module.get_model = lambda *a, **k: (_ for _ in ()).throw(AssertionError("get_model() should not be called"))
    try:
        result = rerank("q", [sc("a", "text")], top_k=1, predict_fn=lambda pairs: [1.0])
        assert result[0].chunk_id == "a"
    finally:
        reranking_module.get_model = original_get_model

"""Unit tests: the shared stock rule, the request-language parsing, keyword
fallback when the embedding model is unavailable, and the assistant's
failure reasons."""
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.ai.forecasting import stock_advice
from src.ai.rag import embeddings, pipeline
from src.ai.rag.bm25_index import BM25Index
from src.ai.rag.faiss_index import FAISSIndex
from src.infrastructure.request_language import normalize_language


@pytest.mark.parametrize("stock, demand, reorder, action, priority", [
    (5, 90, 0, "restock", "high"),        # lasts ~2 days
    (80, 90, 0, "restock", "medium"),     # lasts ~27 days: won't cover 30
    (8, 1, 10, "restock", "medium"),      # at/below the reorder level the business set
    (100, 90, 0, "monitor", "low"),       # covered
    (400, 90, 0, "reduce", "low"),        # ~133 days of cover
    (700, 90, 0, "reduce", "medium"),     # ~233 days of cover
    (50, 0, 0, "monitor", "low"),         # no forecast demand
])
def test_stock_advice(stock, demand, reorder, action, priority):
    advice = stock_advice.advise(stock, demand, reorder_level=reorder, safety_stock=0)
    assert advice["action"] == action
    assert advice["priority"] == priority
    assert advice["suggested_qty"] >= 0


def test_stock_advice_orders_enough_for_the_forecast_and_safety_stock():
    advice = stock_advice.advise(10, 60, reorder_level=0, safety_stock=5)
    assert advice["suggested_qty"] == 55  # 60 + 5 - 10
    assert advice["days_of_cover"] == 5.0


def test_untracked_stock_gets_no_advice():
    assert stock_advice.advise(None, 50)["action"] == "none"


@pytest.mark.parametrize("raw, lang", [("ar-JO,ar;q=0.9", "ar"), ("EN", "en"), ("fr-FR", "fr"), ("de", "en"), (None, "en"), ("", "en")])
def test_normalize_language(raw, lang):
    assert normalize_language(raw) == lang


def _index_with_vectors():
    chunks = [("c1", "delivery takes three days"), ("c2", "returns are accepted within 14 days")]
    vectors = np.eye(2, 4, dtype=np.float32)
    return pipeline.TenantIndex(bm25=BM25Index(chunks), faiss=FAISSIndex(chunks, vectors))


def test_retrieval_falls_back_to_keywords_when_the_embedding_model_is_unavailable():
    index = _index_with_vectors()
    with patch.object(pipeline, "try_embed", return_value=None):
        results = pipeline.retrieve_hybrid(index, "returns policy", top_k=2)
    assert results and results[0].chunk_id == "c2"


def test_retrieval_without_any_vectors_never_loads_the_model():
    chunks = [("c1", "delivery takes three days")]
    index = pipeline.TenantIndex(bm25=BM25Index(chunks), faiss=FAISSIndex([], np.empty((0, 0), dtype=np.float32)))
    with patch.object(pipeline, "try_embed", side_effect=AssertionError("model should not load")):
        results = pipeline.retrieve_hybrid(index, "delivery", top_k=1)
    assert results[0].chunk_id == "c1"


def test_model_load_failure_is_remembered_and_reported_as_unavailable(monkeypatch):
    monkeypatch.setattr(embeddings, "_model_cache", {})
    monkeypatch.setattr(embeddings, "_unavailable_until", 0.0)
    fake_module = MagicMock()
    fake_module.SentenceTransformer.side_effect = OSError("no network")
    with patch.dict("sys.modules", {"sentence_transformers": fake_module}):
        assert embeddings.try_embed(["x"], model_name="missing-model") is None
        assert embeddings.try_embed(["x"], model_name="missing-model") is None
    assert fake_module.SentenceTransformer.call_count == 1  # second call didn't retry the download


def test_documents_are_stored_for_keyword_search_when_embeddings_are_unavailable():
    conn = MagicMock()
    doc = {"document_id": "d1", "file_name": "policy.pdf", "storage_bucket_path": "uploads/x.pdf"}
    with patch.object(pipeline.data_access, "list_documents", return_value=[doc]), \
         patch.object(pipeline.data_access, "fetch_document_text", return_value="Our delivery policy. " * 40), \
         patch.object(pipeline, "try_embed", return_value=None), \
         patch.object(pipeline.data_access, "replace_document_chunks") as replace, \
         patch.object(pipeline.data_access, "mark_document_status") as mark, \
         patch.object(pipeline.data_access, "load_chunks_missing_embeddings", return_value=[]):
        processed = pipeline.ingest_pending_documents(conn, MagicMock(), "t1")
    assert processed == 1
    args = replace.call_args[0]
    assert args[4] is None and args[5] is None  # no vectors, no model version
    mark.assert_called_with(conn, "d1", "Processed")


def test_answers_never_show_internal_labels_and_arabic_sources_are_labelled_in_arabic():
    from src.ai.rag.llm_client import clean_answer_text

    english = clean_answer_text("Carrefour is cheaper on olive oil.\n\nSource: RADAR_CALCULATION, [YOUR_COMPANY_DATA]")
    assert "RADAR_CALCULATION" not in english and "YOUR_COMPANY_DATA" not in english
    assert english.endswith("Source: KEEL calculations, your company data")
    arabic = clean_answer_text("كارفور أرخص في زيت الزيتون من متجرك حاليا.\n\nSource: RADAR_CALCULATION")
    assert "المصدر:" in arabic and "Source:" not in arabic and "حسابات KEEL" in arabic


def test_price_question_routes_to_the_competitor_comparison():
    from src.ai.rag.business_analysis import _COMPETITOR_KEYWORDS, _asks

    for question in ("How do my prices compare?", "Are my products overpriced?", "كيف تقارن أسعاري بالمنافسين؟"):
        assert _asks(question.lower(), _COMPETITOR_KEYWORDS), question

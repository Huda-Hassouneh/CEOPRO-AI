"""Evidence mode: the assistant's answer when the language model can't write one."""
import pytest

from src.ai.rag import evidence_answer, llm_client
from src.ai.rag.retrieval_types import AssembledContext


def _context(query, passages=()):
    text = "\n\n".join(f"[Source {i}]\n{p}" for i, p in enumerate(passages, start=1))
    sources = [{"source_index": i, "chunk_id": f"chunk-{i}", "score": 1.0} for i in range(1, len(passages) + 1)]
    return AssembledContext(query=query, context_text=text, sources=sources)


@pytest.fixture
def names(monkeypatch):
    table = {}
    monkeypatch.setattr(evidence_answer, "_document_names", lambda conn, tenant, ids: {i: table[i] for i in ids if i in table})
    return table


def test_returns_none_when_nothing_real_can_be_shown(names):
    assert evidence_answer.build_evidence_answer(None, "t", _context("hello"), [], "", "en", "not_configured") is None


def test_shows_question_specific_analysis_with_a_localized_lead(names):
    result = evidence_answer.build_evidence_answer(
        None, "t", _context("ما المنتجات التي يجب إعادة طلبها؟"), [("RADAR_CALCULATION", "Restock check:\n- Dates: order 20")], "", "ar", "provider_busy",
    )
    assert result["answer"].startswith("خدمة الكتابة بالذكاء الاصطناعي مشغولة")
    assert "Restock check" in result["answer"]
    assert result["evidence"]["reason"] == "provider_busy"


def test_shows_an_uploaded_document_passage_with_its_file_name(names):
    names["chunk-1"] = ("Returns Policy.pdf", "uploads/x.pdf")
    result = evidence_answer.build_evidence_answer(
        None, "t", _context("what is our return policy", ["Returns are accepted within 14 days."]), [], "", "en", "not_configured",
    )
    assert result["evidence"]["documents"] == [{"document": "Returns Policy.pdf", "generated": False, "text": "Returns are accepted within 14 days."}]


def test_skips_passages_that_share_nothing_with_the_question(names):
    names["chunk-1"] = ("Delivery Policy.pdf", "uploads/d.pdf")
    result = evidence_answer.build_evidence_answer(
        None, "t", _context("what is our return policy", ["Same-day delivery in the city centre."]), [], "", "en", "not_configured",
    )
    assert result is None


def test_never_shows_generated_help_written_for_the_model(names):
    names["chunk-1"] = ("platform_help.txt", "_generated/platform_help.txt")
    result = evidence_answer.build_evidence_answer(
        None, "t", _context("how do I fix an upload error", ["Upload error: always reassure first, then explain."]), [], "", "en", "provider_unavailable",
    )
    assert result is None


def test_sales_summary_drops_the_model_facing_source_notes(names):
    facts = (
        "Sales in the last 30 days (source: invoices.total_amount by issue_date):\n- Revenue 100 JOD from 4 invoices.\n"
        "Current overall sentiment score (source: sentiment_results): 0.4."
    )
    result = evidence_answer.build_evidence_answer(
        None, "t", _context("how were sales last month"), [], "", "en", "not_configured", structured_facts=facts,
    )
    assert "Sales in the last 30 days:\n- Revenue 100 JOD from 4 invoices." in result["answer"]
    assert "invoices.total_amount" not in result["answer"] and "sentiment" not in result["answer"]


def test_answer_query_falls_back_to_evidence_when_the_provider_is_not_configured(monkeypatch):
    monkeypatch.setattr(llm_client, "run_retrieval", lambda *a, **k: _context("how do I add a product"))
    monkeypatch.setattr(llm_client, "build_structured_facts_block", lambda *a, **k: "")
    monkeypatch.setattr(llm_client, "build_financial_facts_block", lambda *a, **k: "")

    def unavailable(*_a, **_k):
        raise llm_client.LLMNotConfiguredError("no key")

    monkeypatch.setattr(llm_client, "_generate_answer_with_usage", unavailable)
    result = llm_client.answer_query(conn=None, tenant_id="t", query_text="how do I add a product")
    assert result["answer_mode"] == "evidence"
    assert result["evidence"]["guide"]
    assert result["token_usage"]["total_tokens"] == 0


def test_answer_query_still_raises_when_there_is_no_evidence(monkeypatch):
    monkeypatch.setattr(llm_client, "run_retrieval", lambda *a, **k: _context("hello"))
    monkeypatch.setattr(llm_client, "build_structured_facts_block", lambda *a, **k: "")

    def unavailable(*_a, **_k):
        raise llm_client.LLMError("down")

    monkeypatch.setattr(llm_client, "_generate_answer_with_usage", unavailable)
    with pytest.raises(llm_client.LLMError):
        llm_client.answer_query(conn=None, tenant_id="t", query_text="hello", include_structured_facts=False)

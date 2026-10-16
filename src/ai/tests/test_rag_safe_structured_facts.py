"""Offline tests for llm_client._safe_structured_facts(): live-facts failures must degrade, not 500."""

from unittest.mock import MagicMock

from src.ai.rag import llm_client


def make_conn(executed):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.execute.side_effect = lambda sql, *a: executed.append(sql)
    return conn


def test_returns_block_on_success(monkeypatch):
    executed = []
    monkeypatch.setattr(llm_client, "build_structured_facts_block", lambda c, t: "facts")
    assert llm_client._safe_structured_facts(make_conn(executed), "t1") == "facts"
    assert executed == ["SAVEPOINT structured_facts;"]


def test_failure_rolls_back_to_savepoint_and_returns_empty(monkeypatch):
    executed = []

    def boom(c, t):
        raise RuntimeError("relation missing")

    monkeypatch.setattr(llm_client, "build_structured_facts_block", boom)
    assert llm_client._safe_structured_facts(make_conn(executed), "t1") == ""
    assert executed == ["SAVEPOINT structured_facts;", "ROLLBACK TO SAVEPOINT structured_facts;"]


def test_answer_query_still_answers_when_facts_fail(monkeypatch):
    from src.ai.rag.retrieval_types import AssembledContext

    monkeypatch.setattr(llm_client, "run_retrieval", lambda *a, **k: AssembledContext("q", "ctx", []))
    monkeypatch.setattr(llm_client, "build_structured_facts_block", lambda c, t: 1 / 0)
    seen = {}

    def fake_generate(context, structured_facts="", history=None):
        seen["facts"] = structured_facts
        return "ok", {}

    monkeypatch.setattr(llm_client, "_generate_answer_with_usage", fake_generate)
    result = llm_client.answer_query(make_conn([]), "t1", "q")
    assert result["answer"] == "ok" and seen["facts"] == ""

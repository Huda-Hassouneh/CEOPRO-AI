"""
Offline (no DB, no LLM, no network) tests for rag/eval/run_eval.py's
deterministic gate-selection check (B12, Phase 2) - the one mode that
always runs and never needs live infrastructure.
"""
from src.ai.rag.eval.run_eval import run_deterministic_gate_check, _predict_gate_hits


def test_run_deterministic_gate_check_never_raises_and_covers_every_case():
    from src.ai.rag.eval.business_copilot_eval_set import EVAL_QUESTIONS
    results = run_deterministic_gate_check()
    assert len(results) == len(EVAL_QUESTIONS)
    ids = {r["id"] for r in results}
    assert ids == {c["id"] for c in EVAL_QUESTIONS}


def test_every_result_has_a_recognized_verdict():
    valid_verdicts = {"PASS", "FAIL", "INFORMATIONAL", "NOT_STATICALLY_CHECKABLE"}
    for result in run_deterministic_gate_check():
        assert result["verdict"] in valid_verdicts


def test_application_knowledge_case_passes_its_own_gate():
    hits = _predict_gate_hits("How do I add a new product?")
    assert hits["application_knowledge"] is True


def test_financial_case_hits_the_financial_gate():
    hits = _predict_gate_hits("Which products are most profitable?")
    assert hits["financial"] is True


def test_unrelated_case_hits_no_gate():
    hits = _predict_gate_hits("what's the capital of France")
    assert not any(hits.values())


def test_no_case_in_the_real_dataset_fails_its_own_expected_category():
    """The real regression this test locks in: run against the actual
    EVAL_QUESTIONS dataset, zero cases should FAIL (a FAIL here means the
    orchestration gates genuinely cannot attempt the grounding a case
    claims to need - a real bug, not a dataset-design choice)."""
    results = run_deterministic_gate_check()
    failures = [r for r in results if r["verdict"] == "FAIL"]
    assert failures == [], f"Unexpected gate-selection failures: {failures}"


def test_answers_are_scored_on_citations_references_and_language():
    from src.ai.rag.eval.run_eval import score_answer, summarize

    case = {"id": "x", "question": "How were my sales?", "expected_grounding": "structured_data"}
    result = {
        "answer": "Revenue was 10 JOD.¹ Maybe more.", "answer_mode": "ai",
        "answer_blocks": [{"type": "paragraph", "claims": [
            {"text": "Revenue was 10 JOD.", "kind": "fact", "refs": [1], "verified": True, "notes": []},
            {"text": "Maybe more.", "kind": "inference", "refs": [], "verified": False, "notes": ["no_evidence"]},
        ]}],
        "references": [{"n": 1, "title": "Sales", "excerpt": "Revenue 10 JOD", "route": "/sales"},
                       {"n": 2, "title": "Broken", "excerpt": "", "route": None}],
        "citation_check": {"issues": 2, "repaired": True}, "token_usage": {"total_tokens": 900},
    }
    score = score_answer(case, result, 3.21)
    assert score["claims_needing_evidence"] == 2 and score["claims_cited_and_verified"] == 1
    assert score["unverified_claims"] == 1 and score["references_complete"] == 1
    assert score["language_ok"] and score["citation_issues_caught"] == 2 and score["latency_seconds"] == 3.21
    arabic = score_answer({**case, "question": "كيف المبيعات؟"}, result, 1.0)
    assert arabic["language_ok"] is False, "an English reply to an Arabic question is a mismatch"
    summary = summarize([score, arabic])
    assert summary["citation_coverage"] == 0.5 and summary["reference_completeness"] == 0.5
    assert summary["language_match"] == 0.5 and summary["unsupported_claims_caught"] == 4


def test_calculation_cases_pass_the_gate_check():
    results = {r["id"]: r for r in run_deterministic_gate_check()}
    assert all(results[case]["verdict"] == "PASS" for case in ("trade-01", "trade-02", "trade-03"))

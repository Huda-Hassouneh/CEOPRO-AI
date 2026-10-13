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

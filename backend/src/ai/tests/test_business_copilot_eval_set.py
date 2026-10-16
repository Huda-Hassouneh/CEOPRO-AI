"""
Sanity tests for rag/eval/business_copilot_eval_set.py - not a scoring
harness (none exists yet - see that module's own docstring), just proof
the dataset itself is well-formed and covers the categories it claims to."""
from src.ai.rag.eval.business_copilot_eval_set import EVAL_QUESTIONS

_VALID_GROUNDING = {"structured_data", "application_knowledge", "market_external", "insufficient_data", "mixed",
                    "calculation"}


def test_every_case_has_required_fields_and_valid_grounding():
    for case in EVAL_QUESTIONS:
        assert case["id"], "every case needs a stable id"
        assert case["question"].strip(), f"{case['id']} has an empty question"
        assert case["expected_grounding"] in _VALID_GROUNDING, f"{case['id']} has an invalid expected_grounding"
        assert case["notes"].strip(), f"{case['id']} has no reviewer notes"


def test_ids_are_unique():
    ids = [case["id"] for case in EVAL_QUESTIONS]
    assert len(ids) == len(set(ids))


def test_covers_every_category_the_design_brief_named():
    categories = {case["category"] for case in EVAL_QUESTIONS}
    assert categories == {"application", "company_financial", "market", "mixed", "edge_case", "trade", "research"}


def test_conversation_memory_pair_exists_and_is_ordered():
    """mix-03/mix-04 are the direct verification of the design brief's own
    "best-selling product -> how much profit did it generate" worked
    example - must exist as an adjacent pair for a reviewer to actually
    run as two chained turns."""
    ids = [case["id"] for case in EVAL_QUESTIONS]
    assert "mix-03" in ids and "mix-04" in ids
    assert ids.index("mix-04") == ids.index("mix-03") + 1

"""The offline question-understanding benchmark (rag/eval/understanding_benchmark.py): every case in both
sets must keep passing, so a rule change that breaks a wording someone relied on fails here."""
import pytest

from src.ai.rag.eval import understanding_benchmark as B


@pytest.mark.parametrize("name, cases", [("dev", B.DEV), ("holdout", B.HOLDOUT)])
def test_every_benchmark_case_is_understood(name, cases):
    failures = [f"{r['q']}: {'; '.join(r['problems'])}" for r in B.evaluate(cases) if not r["passed"]]
    assert not failures, f"{name}: " + " | ".join(failures)

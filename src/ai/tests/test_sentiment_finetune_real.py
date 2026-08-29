"""
Tests finetune.py::evaluate_only() against the real pretrained sentiment
model - same AI_TEST_SENTIMENT opt-in gate as test_sentiment_model_real.py
(downloads/loads an actual ~1.1GB model). This is the module's actual
point: confirming the full evaluate_only() path (load model -> tokenize ->
run inference -> compute spec S25 metrics) works end-to-end against the
real model CEOPRO already runs in production, using a tiny, obviously-
labeled hand-built set - not a claim that 4 examples constitute a real
evaluation set (they don't; see finetune.py's own docstring for what a
real one needs).
"""
import os
import tempfile

import pytest

from src.ai.sentiment.finetune import evaluate_only
from src.ai.sentiment.model import DEFAULT_MODEL_NAME

pytestmark = pytest.mark.skipif(
    not os.getenv("AI_TEST_SENTIMENT"), reason="AI_TEST_SENTIMENT not set - skipping (downloads a real model)"
)


def _write_tiny_eval_set() -> str:
    path = os.path.join(tempfile.gettempdir(), "finetune_real_eval.csv")
    rows = [
        ("This product is amazing, I love it!", "positive"),
        ("Terrible quality, complete waste of money", "negative"),
        ("The product arrived on time", "neutral"),
        ("خدمة ممتازة، أنصح بها بشدة", "positive"),
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write("text,label\n")
        for text, label in rows:
            f.write(f'"{text}",{label}\n')
    return path


def test_evaluate_only_runs_end_to_end_against_the_real_production_model():
    path = _write_tiny_eval_set()
    metrics = evaluate_only(DEFAULT_MODEL_NAME, path)

    assert "eval_accuracy" in metrics
    assert "eval_macro_f1" in metrics
    assert "eval_confusion_matrix" in metrics
    # not asserting a specific accuracy value - 4 examples is not a real
    # eval set, this only confirms the pipeline itself actually runs and
    # produces the right shape of output against the real model.
    assert 0.0 <= metrics["eval_accuracy"] <= 1.0

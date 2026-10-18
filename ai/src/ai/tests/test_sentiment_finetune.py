"""
Tests for sentiment/finetune.py's own logic - dataset loading, the
train/eval split, and metric computation. Does not test fine_tune() itself
end-to-end (an actual training run, even a tiny one, is too slow for a
regular test run and there's no real labeled dataset to train on regardless
- see the module's own docstring). test_sentiment_finetune_real.py covers
evaluate_only() against the real pretrained model.
"""
import os
import tempfile

import numpy as np
import pytest

from src.ai.sentiment.finetune import LabeledExample, _compute_metrics, _train_eval_split, load_labeled_dataset


def _write_csv(rows, header="text,label"):
    path = os.path.join(tempfile.gettempdir(), f"finetune_test_{id(rows)}.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(header + "\n")
        for text, label in rows:
            f.write(f'"{text}",{label}\n')
    return path


def test_load_labeled_dataset_parses_valid_csv():
    path = _write_csv([("Great service", "positive"), ("Terrible", "negative"), ("It was fine", "neutral")])
    examples = load_labeled_dataset(path)
    assert len(examples) == 3
    assert examples[0] == LabeledExample(text="Great service", label="positive")


def test_load_labeled_dataset_normalizes_label_case():
    path = _write_csv([("Great", "POSITIVE")])
    examples = load_labeled_dataset(path)
    assert examples[0].label == "positive"


def test_load_labeled_dataset_rejects_invalid_label():
    path = _write_csv([("Great", "very_positive")])
    with pytest.raises(ValueError, match="row 2"):
        load_labeled_dataset(path)


def test_load_labeled_dataset_rejects_empty_text():
    path = _write_csv([("", "positive")])
    with pytest.raises(ValueError, match="empty 'text'"):
        load_labeled_dataset(path)


def test_load_labeled_dataset_rejects_missing_columns():
    path = os.path.join(tempfile.gettempdir(), "finetune_bad_header.csv")
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write("content,sentiment\nhi,good\n")
    with pytest.raises(ValueError, match="'text' and 'label' columns"):
        load_labeled_dataset(path)


def test_load_labeled_dataset_rejects_empty_file_with_only_header():
    path = _write_csv([])
    with pytest.raises(ValueError, match="zero data rows"):
        load_labeled_dataset(path)


def test_train_eval_split_is_deterministic_given_a_seed():
    examples = [LabeledExample(text=f"t{i}", label="positive") for i in range(10)]
    train1, eval1 = _train_eval_split(examples, eval_split=0.2, seed=42)
    train2, eval2 = _train_eval_split(examples, eval_split=0.2, seed=42)
    assert [e.text for e in train1] == [e.text for e in train2]
    assert [e.text for e in eval1] == [e.text for e in eval2]


def test_train_eval_split_produces_expected_sizes():
    examples = [LabeledExample(text=f"t{i}", label="positive") for i in range(10)]
    train, eval_set = _train_eval_split(examples, eval_split=0.2, seed=1)
    assert len(eval_set) == 2
    assert len(train) == 8


def test_train_eval_split_never_produces_zero_eval_rows_for_a_small_dataset():
    """A 3-row dataset at 0.2 split would round to 0 eval rows without the
    max(1, ...) floor - that would make evaluation silently meaningless."""
    examples = [LabeledExample(text=f"t{i}", label="positive") for i in range(3)]
    _, eval_set = _train_eval_split(examples, eval_split=0.2, seed=1)
    assert len(eval_set) >= 1


def test_train_eval_split_covers_every_example_exactly_once():
    examples = [LabeledExample(text=f"t{i}", label="positive") for i in range(10)]
    train, eval_set = _train_eval_split(examples, eval_split=0.3, seed=7)
    all_texts = sorted(e.text for e in train) + sorted(e.text for e in eval_set)
    assert sorted(all_texts) == sorted(e.text for e in examples)
    assert len(train) + len(eval_set) == len(examples)


def test_compute_metrics_perfect_predictions():
    logits = np.array([[10, 0, 0], [0, 10, 0], [0, 0, 10]])  # argmax -> 0, 1, 2
    labels = np.array([0, 1, 2])
    metrics = _compute_metrics((logits, labels))
    assert metrics["accuracy"] == 1.0
    assert metrics["macro_f1"] == 1.0


def test_compute_metrics_all_wrong_predictions():
    logits = np.array([[10, 0, 0], [10, 0, 0]])  # always predicts class 0
    labels = np.array([1, 2])
    metrics = _compute_metrics((logits, labels))
    assert metrics["accuracy"] == 0.0


def test_compute_metrics_confusion_matrix_shape_matches_class_count():
    logits = np.array([[10, 0, 0], [0, 10, 0], [0, 0, 10], [10, 0, 0]])
    labels = np.array([0, 1, 2, 0])
    metrics = _compute_metrics((logits, labels))
    cm = metrics["confusion_matrix"]
    assert len(cm) == 3
    assert all(len(row) == 3 for row in cm)

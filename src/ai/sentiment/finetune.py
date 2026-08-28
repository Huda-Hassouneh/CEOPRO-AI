"""
CEOPRO AI - Sentiment Model Fine-Tuning & Evaluation Harness (spec S16, S25).

**Status: infrastructure only, not yet run against real data.** No labeled
sentiment dataset exists anywhere in this repo - confirmed, not assumed
(AI_ENGINEERING_PLAN.md section 5's own gap analysis, PENDING_ACTIONS.md).
This module exists so that the moment real labeled data does exist, both
fine-tuning and formal evaluation are one function call away rather than a
from-scratch build. It does not fabricate synthetic training data to make
that call succeed today - see load_labeled_dataset()'s expected CSV shape
below for exactly what's needed and how to check it in.

Why fine-tuning is optional infrastructure, not a default action: spec S7
states plainly, more than once, "Pretrained multilingual models must be
preferred over training models from scratch." model.py's classify() already
uses cardiffnlp/twitter-xlm-roberta-base-sentiment - spec S16's own stated
model choice - unmodified. Fine-tuning it further is a legitimate
enhancement (domain-adapting to CEOPRO's actual review text, improving
Arabic-dialect handling) but is not itself a spec requirement, and running
it without real labeled data would produce a model with no genuine
improvement to show for it - worse, a false sense of having "done"
fine-tuning. CPU-only per the confirmed deployment target
(PENDING_ACTIONS.md #13) - defaults below (small batch size, few epochs)
are chosen for that constraint, not for GPU throughput.

Expected dataset format (CSV, UTF-8): two required columns, `text` and
`label`. `label` must be exactly one of positive/neutral/negative
(case-insensitive - matches sentiment_results.label's CHECK constraint,
see model.py::_label_index_map()). One example row:

    text,label
    "الخدمة ممتازة والسعر مناسب",positive
"""
import csv
import random
from dataclasses import dataclass
from typing import List, Optional, Tuple

import torch
from torch.utils.data import Dataset
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
)

from src.ai.sentiment.model import DEFAULT_MODEL_NAME, MAX_TOKEN_LENGTH, _label_index_map

DEFAULT_EVAL_SPLIT = 0.2
DEFAULT_EPOCHS = 3
DEFAULT_LEARNING_RATE = 2e-5
# Small default - a modest CPU can hold this in memory comfortably; raise
# it explicitly once real hardware/timing is known, don't assume GPU.
DEFAULT_BATCH_SIZE = 8
DEFAULT_SEED = 42


@dataclass
class LabeledExample:
    text: str
    label: str  # "positive" | "neutral" | "negative"


def load_labeled_dataset(path: str) -> List[LabeledExample]:
    """
    Reads the CSV format documented in this module's docstring. Raises
    ValueError with the offending row number for any row missing text,
    missing/blank text, or a label outside positive/neutral/negative -
    fails loudly rather than silently dropping or mislabeling a bad row,
    since a training-data bug is far more expensive to catch later than
    a run that refuses to start.
    """
    examples: List[LabeledExample] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or "text" not in reader.fieldnames or "label" not in reader.fieldnames:
            raise ValueError(f"'{path}' must have 'text' and 'label' columns, found: {reader.fieldnames}")
        for row_num, row in enumerate(reader, start=2):  # header is row 1
            text = (row.get("text") or "").strip()
            label = (row.get("label") or "").strip().lower()
            if not text:
                raise ValueError(f"'{path}' row {row_num}: empty 'text'")
            if label not in ("positive", "neutral", "negative"):
                raise ValueError(
                    f"'{path}' row {row_num}: label '{row.get('label')}' must be "
                    f"positive/neutral/negative (case-insensitive)"
                )
            examples.append(LabeledExample(text=text, label=label))
    if not examples:
        raise ValueError(f"'{path}' has a valid header but zero data rows")
    return examples


def _train_eval_split(
    examples: List[LabeledExample], eval_split: float, seed: int
) -> Tuple[List[LabeledExample], List[LabeledExample]]:
    shuffled = examples[:]
    random.Random(seed).shuffle(shuffled)
    n_eval = max(1, int(len(shuffled) * eval_split))
    return shuffled[n_eval:], shuffled[:n_eval]


class _TokenizedSentimentDataset(Dataset):
    """
    Tokenizes lazily per-item rather than all at once up front - keeps
    peak memory bounded for a larger dataset on a CPU-only machine,
    at the cost of re-tokenizing on every epoch (an acceptable trade at
    the dataset sizes this is realistically run against; revisit if a
    real dataset turns out large enough for that trade to flip).
    """

    def __init__(self, examples: List[LabeledExample], tokenizer, label_index: dict, max_length: int):
        self.examples = examples
        self.tokenizer = tokenizer
        self.label_index = label_index
        self.max_length = max_length

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, idx: int) -> dict:
        example = self.examples[idx]
        encoding = self.tokenizer(
            example.text, truncation=True, max_length=self.max_length, padding="max_length", return_tensors="pt"
        )
        item = {k: v.squeeze(0) for k, v in encoding.items()}
        item["labels"] = torch.tensor(self.label_index[example.label], dtype=torch.long)
        return item


def _compute_metrics(eval_pred) -> dict:
    """
    Spec S25's stated metrics for the sentiment model family: Accuracy,
    Macro F1, Confusion Matrix. (Calibration - the 4th S25 metric - needs
    a separate reliability-diagram/ECE computation over predicted
    probabilities, not a per-batch Trainer metric; left for a follow-up
    once there's a real eval set to calibrate against.) Uses scikit-learn,
    already a project dependency (src/ai/requirements.txt), not a new one.
    """
    from sklearn.metrics import accuracy_score, confusion_matrix, f1_score

    logits, labels = eval_pred
    predictions = logits.argmax(axis=-1)
    return {
        "accuracy": accuracy_score(labels, predictions),
        "macro_f1": f1_score(labels, predictions, average="macro"),
        "confusion_matrix": confusion_matrix(labels, predictions).tolist(),
    }


def fine_tune(
    dataset_path: str,
    output_dir: str,
    base_model: Optional[str] = None,
    eval_split: float = DEFAULT_EVAL_SPLIT,
    epochs: int = DEFAULT_EPOCHS,
    learning_rate: float = DEFAULT_LEARNING_RATE,
    batch_size: int = DEFAULT_BATCH_SIZE,
    seed: int = DEFAULT_SEED,
) -> dict:
    """
    Fine-tunes base_model (default: the same cardiffnlp model model.py
    already uses in production) on dataset_path, saves the result to
    output_dir, and returns the final held-out evaluation metrics. Does
    not touch model_versions (PENDING_ACTIONS.md #31 - the table doesn't
    exist in Final_schema.sql at all) or upload anywhere - output_dir is
    a local path; wiring a fine-tuned model into production (versioning,
    MinIO upload, swapping SENTIMENT_MODEL) is a deliberate separate step,
    not automatic here, since nothing should silently start serving a
    freshly fine-tuned model without a human looking at these metrics
    first.
    """
    base_model = base_model or DEFAULT_MODEL_NAME
    examples = load_labeled_dataset(dataset_path)
    train_examples, eval_examples = _train_eval_split(examples, eval_split, seed)

    tokenizer = AutoTokenizer.from_pretrained(base_model)
    model = AutoModelForSequenceClassification.from_pretrained(base_model)
    label_index = _label_index_map(model)

    train_dataset = _TokenizedSentimentDataset(train_examples, tokenizer, label_index, MAX_TOKEN_LENGTH)
    eval_dataset = _TokenizedSentimentDataset(eval_examples, tokenizer, label_index, MAX_TOKEN_LENGTH)

    training_args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        learning_rate=learning_rate,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="macro_f1",
        seed=seed,
        use_cpu=True,
        report_to=[],  # no wandb/tensorboard side effects by default
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        compute_metrics=_compute_metrics,
    )
    trainer.train()
    metrics = trainer.evaluate()
    trainer.save_model(output_dir)
    tokenizer.save_pretrained(output_dir)
    return metrics


def evaluate_only(model_name_or_path: str, dataset_path: str, batch_size: int = DEFAULT_BATCH_SIZE) -> dict:
    """
    Runs the spec S25 metrics against dataset_path with no training step -
    usable today against the current production model
    (cardiffnlp/twitter-xlm-roberta-base-sentiment) the moment any labeled
    holdout set exists, to finally produce the real numbers
    AI_ENGINEERING_PLAN.md section 5 flags as missing ("not yet - no
    labeled entity gold-set exists"). Also the right tool for comparing a
    fine_tune() output against the base model on the same held-out set,
    to decide whether fine-tuning actually helped before deploying it.
    """
    examples = load_labeled_dataset(dataset_path)
    tokenizer = AutoTokenizer.from_pretrained(model_name_or_path)
    model = AutoModelForSequenceClassification.from_pretrained(model_name_or_path)
    label_index = _label_index_map(model)
    dataset = _TokenizedSentimentDataset(examples, tokenizer, label_index, MAX_TOKEN_LENGTH)

    trainer = Trainer(
        model=model,
        args=TrainingArguments(output_dir="/tmp/ceopro_eval_only", per_device_eval_batch_size=batch_size, use_cpu=True, report_to=[]),
        compute_metrics=_compute_metrics,
    )
    return trainer.evaluate(eval_dataset=dataset)

"""The question-understanding benchmark's dev split stays fully correct, and the
sealed holdout split is unchanged (src/ai/rag/eval/understanding_benchmark/README.md)."""
import hashlib
import json

from scripts.evaluate_understanding import BENCH, load, score_item


def _catalog():
    return json.loads((BENCH / "catalog.json").read_text(encoding="utf-8"))


def test_dev_split_is_fully_understood():
    catalog = _catalog()
    failures = [row for row in (score_item(item, catalog) for item in load("dev")) if not row["correct"]]
    assert failures == []


def test_holdout_split_is_sealed():
    pinned = (BENCH / "holdout.sha256").read_text().split()[0]
    assert hashlib.sha256((BENCH / "holdout.jsonl").read_bytes()).hexdigest() == pinned


def test_three_letter_arabic_product_word_resolves_but_short_english_word_does_not():
    from src.ai.rag.understanding import extract_slots
    catalog = _catalog()
    assert [p["product_id"] for p in extract_slots("كم بعنا من العسل؟", catalog)["products"]] == ["p-honey"]
    assert [p["product_id"] for p in extract_slots("شو رأيهم بالتمر", catalog)["products"]] == ["p-dates"]
    assert "products" not in extract_slots("how much oil", catalog)


def test_imported_as_product_attribute_is_not_a_customs_question():
    from src.ai.rag.understanding import detect_intents
    assert "trade" not in detect_intents("Why do customers prefer imported rice?")
    assert "trade" in detect_intents("What duties apply to imported rice?")
    assert "trade" in detect_intents("How do I import rice from India?")

"""
Regression gate for the price comparison classifier: scores the committed labelled set (rules only, no model) and fails
if the numbers that put a wrong price in front of an owner get worse. Raise the floors when accuracy improves; never
lower them to make a change pass. Plus the specific name classes fixed on 2026-10-20.
"""
import pytest

from scripts.price_comparison_eval import DEFAULT_CSV
from src.market_scraper.price_comparison import attributes, evaluate, tiers

# Measured 2026-10-20 on the whole set (dev + holdout): accuracy 78.1 %, exact precision 100 %, like-for-like 99.4 %,
# false relations 19.0 %, direction 97.9 %. Floors sit a little under so a single pair does not flip the gate.
FLOORS = {"accuracy": 0.77, "accuracy_when_settled": 0.89, "exact_precision": 0.98, "like_for_like_precision": 0.98,
          "direction_accuracy": 0.95}
CEILINGS = {"false_relation_rate": 0.22, "missed_relation_rate": 0.09}


@pytest.fixture(scope="module")
def report():
    return evaluate.score(evaluate.load_labelled(DEFAULT_CSV))


@pytest.mark.parametrize("metric,floor", FLOORS.items())
def test_accuracy_does_not_drop(report, metric, floor):
    assert report[metric] >= floor, f"{metric} fell to {report[metric]} (floor {floor})"


@pytest.mark.parametrize("metric,ceiling", CEILINGS.items())
def test_error_rates_do_not_rise(report, metric, ceiling):
    assert report[metric] <= ceiling, f"{metric} rose to {report[metric]} (ceiling {ceiling})"


def classify(own, own_price, item, item_price):
    return tiers.classify(attributes.parse_offer(own), attributes.parse_offer(item), own_price, item_price)


@pytest.mark.parametrize("own,item", [
    ("PVC Pipe 110mm (per m)", "PVC Pipe 160mm per meter"),
    ("Galvanized Sheet 1.2mm", "Galvanized Sheet 1.5mm"),
    ("Power Bank 20000mAh", "Power Bank 10000mAh"),
])
def test_a_different_spec_is_never_exact(own, item):
    result = classify(own, 10, item, 10)
    assert result is None or result.tier == tiers.SIMILAR


def test_the_same_spec_written_two_ways_is_still_exact():
    assert classify("PVC Pipe 110 mm", 10, "PVC Pipe 110mm", 10).tier == tiers.EXACT


def test_half_a_day_is_not_equivalent_to_a_day():
    result = classify("Atelier de transformation (journée)", 100, "Atelier de transformation demi-journée", 60)
    assert result.tier == tiers.SIMILAR


def test_two_days_still_scale_from_one():
    assert classify("Workshop 2 days", 200, "Workshop 1 day", 100).tier == tiers.EQUIVALENT


def test_platter_is_a_format_word_not_a_different_dish():
    assert classify("Mixed Grill Platter", 20, "Mixed Grill", 20).tier == tiers.EXACT


@pytest.mark.parametrize("own,item", [
    ("Robe en lin Blanc - Taille M", "Robe en lin Sable Taille M"),
    ("Djellaba laine - Taille M", "Djellaba coton Taille M"),
    ("Pantalon fluide noir - Taille 38", "Pantalon fluide beige Taille 38"),
])
def test_colour_or_fabric_variants_are_similar(own, item):
    assert classify(own, 100, item, 100).tier == tiers.SIMILAR


def test_a_different_garment_in_the_same_colour_is_not_a_colour_variant():
    result = classify("Robe en lin Blanc - Taille M", 100, "Robe de soirée Blanc Taille M", 100)
    assert result is None or result.reasons[0]["code"] != "variant_differs" or result.tier == tiers.SIMILAR


def _labelled(own, item, label, direction=""):
    return {"id": "w1", "own_name": own, "own_name_alt": "", "own_price": 5.0, "item_name": item, "item_price": 5.0,
            "label": label, "direction": direction, "kind": ""}


def test_merging_a_worksheet_assigns_ids_skips_duplicates_and_keeps_the_split():
    existing = [{**_labelled("Cheese burger", "Cheese burger", "EXACT"), "id": "pc041"}]
    new = [_labelled("Cheese burger", " cheese  BURGER ", "EXACT"), _labelled("Tea 100g", "Tea 100g", "EXACT"),
           _labelled("Tea 100g", "Tea 200g", "SIMILAR", "own_leaner")]
    added, skipped = evaluate.merge_labelled(existing, new, "Acme (JO)", "holdout")
    assert skipped == 1 and [r["id"] for r in added] == ["pc042", "pc043"]
    assert all(r["split"] == "holdout" and r["company"] == "Acme (JO)" and r["kind"] == "clear" for r in added)
    again, skipped_again = evaluate.merge_labelled(existing + added, new, "Acme (JO)")
    assert again == [] and skipped_again == 3


def test_merge_rejects_a_bad_split_or_direction():
    with pytest.raises(ValueError):
        evaluate.merge_labelled([], [_labelled("a b", "a c", "EXACT")], "x", "all")
    with pytest.raises(ValueError):
        evaluate.merge_labelled([], [_labelled("a b", "a c", "SIMILAR", "sideways")], "x")

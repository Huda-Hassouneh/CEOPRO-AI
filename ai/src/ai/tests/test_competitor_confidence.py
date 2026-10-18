from src.ai.pricing.competitor_confidence import (
    LABEL_HIGH, LABEL_LOW, LABEL_MEDIUM, compute_confidence, confidence_label,
)


def _score(**overrides):
    base = dict(
        category_similarity=None, product_match_rate=0.0, matched_product_count=0, distance_km=None,
        strategic_match_rate=0.6,
    )
    base.update(overrides)
    return compute_confidence(**base)


def test_same_category_nearby_well_evidenced_is_high():
    result = _score(category_similarity=1.0, distance_km=1.0, has_website=True, has_address=True, has_rating=True)
    assert result.label == LABEL_HIGH and result.score > 90


def test_same_category_beats_related_category_beats_unknown():
    same = _score(category_similarity=1.0, distance_km=5, has_website=True).score
    related = _score(category_similarity=0.67, distance_km=5, has_website=True).score
    broad = _score(category_similarity=0.5, distance_km=5, has_website=True).score
    assert same > related > broad


def test_product_overlap_at_the_strategic_bar_counts_fully():
    at_bar = _score(category_similarity=1.0, product_match_rate=0.6, matched_product_count=3)
    below = _score(category_similarity=1.0, product_match_rate=0.15, matched_product_count=1)
    assert at_bar.score > below.score


def test_no_mapped_products_leaves_the_signal_out_rather_than_scoring_zero():
    domain_find = _score(category_similarity=1.0)
    assert domain_find.score >= 75  # not dragged down by a missing product signal


def test_distance_far_away_lowers_the_score():
    near = _score(category_similarity=1.0, distance_km=1).score
    far = _score(category_similarity=1.0, distance_km=45).score
    assert near > far


def test_beyond_the_radius_floors_proximity_at_zero_not_negative():
    assert _score(category_similarity=1.0, distance_km=500).score >= 0


def test_everything_unknown_is_low_not_an_error():
    result = _score()
    assert result.label == LABEL_LOW
    assert "Category could not be determined" in result.reasons


def test_reasons_explain_the_score():
    result = _score(
        category_similarity=1.0, product_match_rate=0.3, matched_product_count=2, distance_km=2.5,
        category_label="food > snacks > burger",
    )
    joined = " | ".join(result.reasons)
    assert "Same business category (food > snacks > burger)" in joined
    assert "2 of your products" in joined
    assert "2.5 km away" in joined


def test_label_thresholds():
    assert confidence_label(70) == LABEL_HIGH
    assert confidence_label(69.9) == LABEL_MEDIUM
    assert confidence_label(45) == LABEL_MEDIUM
    assert confidence_label(44.9) == LABEL_LOW


# --- spec S20: configurable, transparent weights ---

import pytest

from src.ai.pricing.competitor_confidence import DEFAULT_WEIGHTS, WEIGHTS_ENV_VAR, resolve_weights


def test_defaults_are_used_with_no_configuration(monkeypatch):
    monkeypatch.delenv(WEIGHTS_ENV_VAR, raising=False)
    assert resolve_weights() == DEFAULT_WEIGHTS


def test_weights_are_configurable_from_the_environment(monkeypatch):
    monkeypatch.setenv(WEIGHTS_ENV_VAR, "category=1, proximity=0.5")
    resolved = resolve_weights()
    assert resolved["category"] == 1.0 and resolved["proximity"] == 0.5
    assert resolved["products"] == DEFAULT_WEIGHTS["products"]


def test_explicit_weights_override_the_environment(monkeypatch):
    monkeypatch.setenv(WEIGHTS_ENV_VAR, "category=1")
    assert resolve_weights({"category": 2})["category"] == 2.0


def test_invalid_configuration_is_ignored_not_fatal(monkeypatch):
    monkeypatch.setenv(WEIGHTS_ENV_VAR, "category=abc,bogus=3,products=-1,proximity")
    assert resolve_weights() == DEFAULT_WEIGHTS


def test_changing_weights_changes_the_ranking():
    near_wrong_category = _score(category_similarity=0.5, distance_km=1, weights={"category": 0.1, "proximity": 0.9})
    far_right_category = _score(category_similarity=1.0, distance_km=45, weights={"category": 0.1, "proximity": 0.9})
    assert near_wrong_category.score > far_right_category.score


def test_breakdown_is_transparent_and_adds_up_to_the_score():
    result = _score(
        category_similarity=1.0, product_match_rate=0.3, matched_product_count=2, distance_km=5.0,
        has_website=True, has_address=True,
    )
    assert {item["signal"] for item in result.breakdown} == {"category", "products", "proximity", "evidence"}
    assert sum(item["weight"] for item in result.breakdown) == pytest.approx(1.0, abs=0.01)
    assert sum(item["contribution"] for item in result.breakdown) == pytest.approx(result.score, abs=0.2)


def test_unknown_signals_are_left_out_of_the_breakdown():
    result = _score(category_similarity=1.0)
    assert "proximity" not in {item["signal"] for item in result.breakdown}
    assert "products" not in {item["signal"] for item in result.breakdown}

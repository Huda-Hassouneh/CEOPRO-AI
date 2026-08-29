"""
Unit tests for template_detection.py. This module had zero test coverage
before this file (found during a post-merge QA pass) - a real bug was
caught immediately once it was actually tested: snake_case headers
("product_name", "unit_price" - Final_schema.sql's own column-naming
convention, and the shape any database/API export naturally produces)
never matched HEADER_SYNONYMS, because _normalize_header() only collapsed
whitespace and never folded underscores to spaces. A file with perfectly
recognizable fields, just snake_case instead of space-separated, silently
fell through to FALLBACK/NER extraction instead of the precise STRICT
mapping it should have gotten.
"""
from src.ai.extraction.template_detection import TemplateMode, build_header_mapping, detect_template


def test_space_separated_synonyms_match_strict_mode():
    result = detect_template(["product name", "quantity", "unit price"])
    assert result.mode == TemplateMode.STRICT
    assert result.header_mapping == {
        "product name": "product_name",
        "quantity": "quantity",
        "unit price": "unit_price",
    }


def test_snake_case_headers_also_match_strict_mode():
    """Regression test: snake_case headers must match the same synonyms
    their space-separated spelling does, not silently fall back to NER."""
    result = detect_template(["product_name", "quantity", "unit_price"])
    assert result.mode == TemplateMode.STRICT
    assert result.header_mapping == {
        "product_name": "product_name",
        "quantity": "quantity",
        "unit_price": "unit_price",
    }
    assert result.coverage_ratio == 1.0


def test_mixed_case_and_whitespace_headers_still_match():
    result = detect_template(["  Product_Name ", "QUANTITY", "Unit_Price"])
    assert result.mode == TemplateMode.STRICT


def test_underscore_synonym_entries_still_resolve_correctly():
    """HEADER_SYNONYMS already has some underscore-containing entries
    (e.g. "prix_unitaire") coexisting with a space-separated spelling of
    the same synonym - confirms folding underscores to spaces doesn't
    make those two entries collide or resolve to different fields. Uses
    build_header_mapping() directly (not detect_template()) since this is
    about the synonym lookup itself, not the STRICT/FALLBACK decision -
    detect_template() always returns an empty mapping in FALLBACK mode,
    and these 2 headers alone don't meet STRICT_MODE_REQUIRED_FIELDS."""
    mapping = build_header_mapping(["prix_unitaire", "prix unitaire"])
    assert mapping["prix_unitaire"] == "unit_price"
    assert mapping["prix unitaire"] == "unit_price"


def test_missing_required_fields_falls_back():
    result = detect_template(["product_name", "notes"])
    assert result.mode == TemplateMode.FALLBACK
    assert result.header_mapping == {}


def test_unrecognized_headers_fall_back():
    result = detect_template(["a_random_column", "another_one", "yet_another"])
    assert result.mode == TemplateMode.FALLBACK
    assert result.matched_fields == set()

"""
match_competitor_records() and its tests were removed along with the schema
fork adoption - Final_schema.sql's competitor_product_mappings resolves a
competitor price to a product_id via a real FK at mapping-creation time, so
pricing/ no longer fuzzy-matches at query time (see matching.py's module
docstring, pricing/data_access.py's module docstring). similarity() itself
is still used directly by extraction/catalog_matching.py.
"""

from src.ai.pricing.matching import similarity


def test_similarity_identical_strings_is_one():
    assert similarity("Sunscreen SPF 50", "Sunscreen SPF 50") == 1.0


def test_similarity_is_case_and_whitespace_insensitive():
    assert similarity("  Sunscreen SPF 50 ", "sunscreen spf 50") == 1.0


def test_similarity_different_products_is_low():
    assert similarity("Sunscreen SPF 50", "Moisturizer Lotion") < 0.5

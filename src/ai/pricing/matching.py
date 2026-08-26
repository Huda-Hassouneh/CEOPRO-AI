"""
CEOPRO AI - Name-Similarity Matching.
Historically used by pricing/pipeline.py to fuzzy-match competitor_prices'
free-text product_name_captured against our own catalog. Final_schema.sql
removed that free-text field: competitor_product_mappings now resolves a
competitor price to a specific product_id via a real FK at mapping-creation
time, not at query time, so pricing/ no longer needs fuzzy matching at all
(see pricing/data_access.py's module docstring). The old
match_competitor_records() function that did that matching has been removed
- it would silently compare the wrong fields against the new schema's data
shape (competitor name where a captured product name used to be).

similarity() itself is kept - it's a general-purpose, spec S37-aligned
fuzzy-match primitive, and extraction/catalog_matching.py still uses it
directly for PRODUCT/COMPETITOR entity matching, which is an unrelated,
still-valid use case.
"""

from difflib import SequenceMatcher


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()

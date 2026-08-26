"""
CEOPRO AI - Rule-Based Extraction Orchestrator (spec S15).
Combines regex-pattern extraction (structurally-regular entities) with
catalog matching (PRODUCT/COMPETITOR names). Pure function, no database
access - pipeline.py is what loads source text and persists the result.
"""

from typing import List, Optional

from src.ai.extraction.catalog_matching import find_catalog_mentions
from src.ai.extraction.regex_patterns import ExtractedEntity, extract_all


def extract_entities(
    text: str, known_product_names: Optional[List[str]] = None, known_competitor_names: Optional[List[str]] = None
) -> List[ExtractedEntity]:
    entities = extract_all(text)

    if known_product_names:
        entities.extend(find_catalog_mentions(text, known_product_names, "PRODUCT"))
    if known_competitor_names:
        entities.extend(find_catalog_mentions(text, known_competitor_names, "COMPETITOR"))

    return sorted(entities, key=lambda e: e.start)

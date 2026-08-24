"""
CEOPRO AI - Catalog-Based Entity Matching (spec S15: PRODUCT, SUPPLIER,
COMPETITOR entity types). These aren't pattern-shaped like MONEY/DATE/EMAIL -
they're look-ups against a tenant's own known names, so they're matched
against a catalog rather than a regex. Reuses the same name-similarity
approach already used for competitor price matching (spec S22: shared,
consistent approach rather than reinventing per module) rather than
duplicating a second fuzzy-matching implementation.
"""

import re
from typing import List

from src.ai.pricing.matching import similarity
from src.ai.extraction.regex_patterns import ExtractedEntity

DEFAULT_MATCH_THRESHOLD = 0.80


def find_catalog_mentions(
    text: str, known_names: List[str], entity_type: str, threshold: float = None
) -> List[ExtractedEntity]:
    """
    Scans `text` for substrings that closely match one of `known_names`
    (e.g. a tenant's own product names, or their tracked competitors).
    Candidate spans are generated from capitalized word runs (Latin script)
    and from Arabic-script word runs (see _candidate_spans - Arabic has no
    capitalization signal, so it needs its own generation rule), then
    scored against the catalog - conservative by design (spec S37:
    "Product Matching: Use rules and fuzzy matching with more manual
    confirmation"), not exhaustive substring search, which would be far too
    slow and far too prone to false positives on ordinary text.
    """
    threshold = DEFAULT_MATCH_THRESHOLD if threshold is None else threshold
    if not known_names:
        return []

    candidate_spans = _candidate_spans(text)
    entities = []
    for start, end, candidate_text in candidate_spans:
        best_name, best_score = None, 0.0
        for name in known_names:
            score = similarity(candidate_text, name)
            if score > best_score:
                best_name, best_score = name, score

        if best_score >= threshold:
            entities.append(
                ExtractedEntity(entity_type=entity_type, text=candidate_text, start=start, end=end, normalized_value=best_name)
            )

    return entities


_CAPITALIZED_RUN_PATTERN = re.compile(r"\b[A-Z][\w'-]*(?:\s+[A-Z0-9][\w'-]*)*\b")

# Fix: the pattern above requires a leading [A-Z], so it never generates a
# candidate span for a catalog name written entirely in Arabic script (e.g.
# a product called "هاتف ذكي"). On a platform whose spec claims full
# Arabic/English parity, that meant catalog matching (PRODUCT/COMPETITOR)
# was silently English-only. Arabic has no capitalization to key off, so
# instead this treats any run of up to 5 Arabic words as a candidate and
# lets the existing similarity threshold do the filtering - the same
# "generate broadly, then score conservatively" design as the Latin path.
_ARABIC_RUN_PATTERN = re.compile(r"[\u0600-\u06FF]+(?:\s+[\u0600-\u06FF]+){0,4}")


def _candidate_spans(text: str):
    spans = list(_capitalized_run_spans(text)) + list(_arabic_run_spans(text))
    spans.sort(key=lambda s: s[0])
    return spans


def _capitalized_run_spans(text: str):
    for m in _CAPITALIZED_RUN_PATTERN.finditer(text):
        yield m.start(), m.end(), m.group(0)


def _arabic_run_spans(text: str):
    for m in _ARABIC_RUN_PATTERN.finditer(text):
        yield m.start(), m.end(), m.group(0)


# Still open (not fixed here - needs more than regex):
# a genuinely mixed-script single entity, e.g. a product name like
# "iPhone ١٥ برو" spanning Latin + Arabic-Indic digits + Arabic in one
# logical run, still generates as separate candidate spans above rather
# than one merged span. Merging that correctly needs script-transition-
# aware tokenization, not a regex tweak - flagged as a known ceiling of
# the zero-cost regex tier, same as in the extraction module's docstring.

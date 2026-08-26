"""
CEOPRO AI - Extraction Orchestrator.
Combines the deterministic regex tier (regex_patterns.extract_all) with
tenant-scoped catalog matching (catalog_matching.find_catalog_mentions,
via the catalog_cache cache-aside wrapper) into one canonical entity list,
then resolves any overlapping spans between the two tiers.
"""
from typing import List, Optional

from src.ai.extraction.regex_patterns import ExtractedEntity, extract_all
from src.ai.extraction.catalog_cache import get_known_names
from src.ai.extraction.catalog_matching import find_catalog_mentions

# Higher number = wins when spans overlap. Anchored/keyword-triggered types
# (EMAIL, INVOICE_ID/ORDER_ID, catalog PRODUCT/COMPETITOR) are the most
# specific and win first; CURRENCY is lowest because a bare currency code
# match is almost always fully contained inside a MONEY match and should
# yield to it, not duplicate it (e.g. "JOD 18.00" -> keep MONEY, drop the
# standalone CURRENCY "JOD" that's part of the same span).
_TYPE_PRIORITY = {
    "EMAIL": 100,
    "INVOICE_ID": 90,
    "ORDER_ID": 90,
    "PRODUCT": 80,
    "COMPETITOR": 80,
    "DATE": 70,
    "MONEY": 60,
    "DISCOUNT": 55,
    "PERCENT": 50,
    "PHONE": 40,
    "CURRENCY": 10,
}
_DEFAULT_PRIORITY = 30


def resolve_overlaps(entities: List[ExtractedEntity]) -> List[ExtractedEntity]:
    """
    Regex patterns and catalog matches can legitimately fire on overlapping
    spans of the same text (a MONEY match containing a standalone CURRENCY
    code; a PRODUCT catalog hit overlapping a PHONE false-positive). Greedy
    interval selection by (type priority, span length) descending: highest-
    priority / longest match wins, everything it overlaps is dropped.
    PENDING (no functional change in this pass): this ranks by priority
    tier only, not by the underlying match confidence - a PRODUCT catalog
    hit just above the 0.80 similarity threshold always beats a
    well-formed MONEY match on overlap, even when the catalog match is the
    weaker signal in that instance. Blending priority with confidence is a
    reasonable follow-up, not done here to avoid changing ranking behavior
    without data to validate the new ordering against.
    Also out of scope for this tier entirely: context-dependent
    disambiguation ("Order 42" the entity vs. "the 42nd order" the
    ordinal). That needs the transformer/EntityRuler tier spec S15 lists
    as the next option above regex/fuzzy matching - no amount of overlap
    resolution here can recover context regex never captured.
    """
    def priority(e: ExtractedEntity):
        return (_TYPE_PRIORITY.get(e.entity_type, _DEFAULT_PRIORITY), e.end - e.start)
    accepted: List[ExtractedEntity] = []
    occupied: List[tuple] = []
    for entity in sorted(entities, key=priority, reverse=True):
        if any(entity.start < end and start < entity.end for start, end in occupied):
            continue
        accepted.append(entity)
        occupied.append((entity.start, entity.end))
    return sorted(accepted, key=lambda e: e.start)


def extract_entities(
    text: str,
    tenant_id: Optional[str] = None,
    redis_client=None,
    conn=None,
    decimal_style: Optional[str] = None,
    day_first: Optional[bool] = None,
) -> List[ExtractedEntity]:
    """
    Canonical entry point for the extraction pipeline: regex tier +
    catalog tier, merged and overlap-resolved.

    Catalog matching (PRODUCT/COMPETITOR) is optional and only runs when
    tenant_id, redis_client, and conn are all supplied - callers doing
    regex-only extraction (e.g. a quick preview with no tenant context)
    can omit them and get regex results alone, overlap-resolved.

    decimal_style/day_first override the regex tier's date/decimal
    convention for this call. This function does not resolve them itself
    (that would mean one companies-table query per extract_entities call -
    per row, in a file-processing loop, that's one query per row). Callers
    processing a whole file should resolve the tenant's locale once via
    locale_config.get_tenant_locale() and pass the result into every
    extract_entities call for that file - see ingestion_pipeline.py.
    """
    entities: List[ExtractedEntity] = list(extract_all(text, decimal_style, day_first))

    if tenant_id is not None and redis_client is not None and conn is not None:
        product_names = get_known_names(redis_client, conn, tenant_id, "products")
        entities.extend(find_catalog_mentions(text, product_names, "PRODUCT"))

        competitor_names = get_known_names(redis_client, conn, tenant_id, "competitors")
        entities.extend(find_catalog_mentions(text, competitor_names, "COMPETITOR"))

    return resolve_overlaps(entities)

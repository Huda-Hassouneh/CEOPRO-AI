"""
CEOPRO AI - Extraction Orchestrator.
Combines the deterministic regex tier with tenant-scoped catalog
matching into one canonical entity list, then resolves overlapping spans
between the two tiers.
"""
from typing import List, Optional

from src.ai.extraction.regex_patterns import ExtractedEntity, extract_all
from src.ai.extraction.catalog_cache import get_known_names
from src.ai.extraction.catalog_matching import find_catalog_mentions

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
    Greedy interval selection by (type priority, span length) descending:
    highest-priority / longest match wins, everything it overlaps is
    dropped.
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
) -> List[ExtractedEntity]:
    """
    Canonical entry point: regex tier + catalog tier, merged and
    overlap-resolved. Catalog matching only runs when tenant_id,
    redis_client, and conn are all supplied.
    """
    entities: List[ExtractedEntity] = list(extract_all(text))

    if tenant_id is not None and redis_client is not None and conn is not None:
        product_names = get_known_names(redis_client, conn, tenant_id, "products")
        entities.extend(find_catalog_mentions(text, product_names, "PRODUCT"))

        competitor_names = get_known_names(redis_client, conn, tenant_id, "competitors")
        entities.extend(find_catalog_mentions(text, competitor_names, "COMPETITOR"))

    return resolve_overlaps(entities)

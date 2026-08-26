"""
CEOPRO AI - Tenant Catalog Cache Wrapper (Redis Cache-Aside Scheme).
"""
import json
from typing import List, Optional

CACHE_TTL_SECONDS = 300


def _cache_key(tenant_id: str, entity_kind: str) -> str:
    return f"catalog:{tenant_id}:{entity_kind}"


def get_known_names(
    redis_client,
    conn,
    tenant_id: str,
    entity_kind: str,
) -> List[str]:
    from src.ai.extraction.data_access import load_known_competitor_names, load_known_product_names
    entity_loaders = {
        "products": load_known_product_names,
        "competitors": load_known_competitor_names,
    }
    if entity_kind not in entity_loaders:
        raise ValueError(f"Unknown entity_kind: {entity_kind!r}")
    key = _cache_key(tenant_id, entity_kind)
    cached = redis_client.get(key)
    if cached is not None:
        return json.loads(cached)
    names = entity_loaders[entity_kind](conn, tenant_id)
    redis_client.set(key, json.dumps(names), ex=CACHE_TTL_SECONDS)
    return names


def invalidate(redis_client, tenant_id: str, entity_kind: Optional[str] = None) -> None:
    if entity_kind is not None:
        redis_client.delete(_cache_key(tenant_id, entity_kind))
        return
    redis_client.delete(
        _cache_key(tenant_id, "products"),
        _cache_key(tenant_id, "competitors"),
    )

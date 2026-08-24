"""
CEOPRO AI - Extraction Catalog Data Access.
Reads known product/competitor names to match against (read-only, existing
tables). Nothing is written here - there is no `extracted_entity` table yet
(PENDING_ACTIONS.md #4), so extraction results have nowhere to persist to.

PENDING (no functional change in this pass): known_names is re-queried from
PostgreSQL on every call with no caching. Fine at demo/current scale; under
high ingestion volume (e.g. batch document processing calling
find_catalog_mentions() per document) this becomes a repeated-query hot
path. Worth a per-tenant cache with explicit invalidation on product/
competitor writes before that becomes a bottleneck - deliberately not
added here since a wrong invalidation rule is worse than no cache.
"""

from typing import List


def load_known_product_names(conn, tenant_id: str) -> List[str]:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT product_name FROM products WHERE tenant_id = %s AND deleted_at IS NULL;", (tenant_id,)
        )
        return [row[0] for row in cursor.fetchall()]


def load_known_competitor_names(conn, tenant_id: str) -> List[str]:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT competitor_name FROM competitors WHERE tenant_id = %s AND is_active = TRUE;", (tenant_id,)
        )
        return [row[0] for row in cursor.fetchall()]

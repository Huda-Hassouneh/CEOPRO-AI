"""
CEOPRO AI - Extraction Catalog Data Access.
Reads known product/competitor names to match against (read-only, existing tables).
"""
from typing import List


def load_known_product_names(conn, tenant_id: str) -> List[str]:
    """
    products.product_name is JSONB (multilingual, e.g. {"en": "...", "ar": "..."}) -
    every language variant is returned as its own candidate name, not just one,
    so catalog matching can catch a mention in any of the tenant's supported
    languages (spec S8 Arabic-English code-switching), not only the tenant's
    single preferred_language.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT product_name FROM products WHERE tenant_id = %s AND deleted_at IS NULL;", (tenant_id,)
        )
        names = []
        for (product_name,) in cursor.fetchall():
            if isinstance(product_name, dict):
                names.extend(v for v in product_name.values() if isinstance(v, str) and v)
            elif isinstance(product_name, str):
                names.append(product_name)
        return names


def load_known_competitor_names(conn, tenant_id: str) -> List[str]:
    """
    The old standalone `competitors` table no longer exists - competitors are
    now a global catalog (global_competitors) a tenant opts into tracking
    (tenant_competitors). Only names this tenant actually tracks are returned,
    matching the old table's is_active filter's intent (don't match against
    competitors this tenant doesn't care about).
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT gc.competitor_name
            FROM tenant_competitors tc
            JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
            WHERE tc.tenant_id = %s AND tc.is_tracked = TRUE;
            """,
            (tenant_id,),
        )
        return [row[0] for row in cursor.fetchall()]

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

similarity() itself is kept as the shared spec-aligned fuzzy-match primitive.
The market scraper uses it before promoting mapped observations (minimum
score 0.82), and extraction/catalog_matching.py uses it for entity matching.

create_competitor_mapping() is the other half of "mapping-creation time"
mentioned above: confirmed by grep before writing it that nothing in this
codebase - not src/market_scraper/, not src/ai/pricing/ - ever actually
INSERTs a competitor_product_mappings row; every mapping in this repo's own
tests is created by hand via raw SQL. This is the one place a mapping
should be created going forward (by a human/tenant feeding in a competitor
manually, or any future automated discovery pipeline), so the two logical
flaws a real deployment would otherwise hit are caught in one place: a
geographically irrelevant match (a competitor with no presence in any
country this tenant operates in - e.g. matching an India-only business to
a China-only restaurant) and a manufacturer mistaken for a competitor (the
brand that makes a product is not a rival seller of it).
"""

import uuid
from difflib import SequenceMatcher


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()


class CompetitorMappingError(ValueError):
    """Raised when a proposed competitor mapping fails a geographic-relevance or manufacturer-exclusion check."""


def create_competitor_mapping(conn, tenant_id: str, global_competitor_id: str, product_id: str) -> str:
    """
    Creates one competitor_product_mappings row, but only after two checks
    neither the schema nor any other code enforces:

    1. Manufacturer exclusion: refuses if global_competitors.is_manufacturer
       is TRUE for this competitor - a product's own manufacturer/brand
       owner is not a rival seller of it, and treating it as one would
       corrupt every downstream price comparison (their price is closer to
       a wholesale/MSRP reference than a competing retail offer).
    2. Geographic relevance: refuses unless the competitor's country_code
       is one of this tenant's own companies.country_code or
       companies.operating_countries - a competitor with no presence in
       any country this tenant actually operates in isn't a real
       competitor for pricing purposes, regardless of how well its product
       name matches (name similarity alone, e.g. similarity() above, has
       no concept of geography).

    Raises CompetitorMappingError (never a bare KeyError/TypeError) with a
    human-readable reason on either failure, or if the tenant/competitor
    id doesn't exist at all. Does not call conn.commit() - same convention
    as every other write in src/ai/pricing/, the caller controls the
    transaction boundary.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT country_code, is_manufacturer, competitor_name FROM global_competitors "
            "WHERE global_competitor_id = %s;",
            (global_competitor_id,),
        )
        competitor_row = cursor.fetchone()
        if competitor_row is None:
            raise CompetitorMappingError(f"global_competitor_id {global_competitor_id} does not exist")
        competitor_country, is_manufacturer, competitor_name = competitor_row

        if is_manufacturer:
            raise CompetitorMappingError(
                f"'{competitor_name}' is flagged as this product's manufacturer, not a retail "
                f"competitor - refusing to create a competitor mapping for it."
            )

        cursor.execute(
            "SELECT country_code, operating_countries FROM companies WHERE tenant_id = %s;",
            (tenant_id,),
        )
        tenant_row = cursor.fetchone()
        if tenant_row is None:
            raise CompetitorMappingError(f"tenant {tenant_id} does not exist")
        tenant_country, operating_countries = tenant_row
        relevant_countries = {tenant_country, *(operating_countries or [])}

        if not competitor_country:
            raise CompetitorMappingError(
                f"'{competitor_name}' has no country_code on record - cannot verify it is a "
                f"geographically relevant competitor for a tenant operating in {sorted(relevant_countries)}."
            )
        if competitor_country not in relevant_countries:
            raise CompetitorMappingError(
                f"'{competitor_name}' operates in {competitor_country}, but this tenant only operates "
                f"in {sorted(relevant_countries)} - refusing to map a geographically irrelevant competitor."
            )

        # competitor_product_mappings' own FK requires a tenant_competitors
        # row to already exist (a tenant must be "tracking" a global
        # competitor before mapping a product to it) - ensured here rather
        # than pushed onto every caller, since by this point both checks
        # above have already passed and there's nothing left to gate.
        cursor.execute(
            "INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked) "
            "VALUES (%s, %s, TRUE) "
            "ON CONFLICT (tenant_id, global_competitor_id) DO NOTHING;",
            (tenant_id, global_competitor_id),
        )

        mapping_id = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO competitor_product_mappings (mapping_id, tenant_id, global_competitor_id, product_id, is_active) "
            "VALUES (%s, %s, %s, %s, TRUE);",
            (mapping_id, tenant_id, global_competitor_id, product_id),
        )
    return mapping_id

"""
KEEL - Explicit commercial Target Markets (persistence).

A Target Market is a country, a free-text region, or a "compete globally"
declaration that a tenant has explicitly stated it wants to COMPETE IN
commercially - deliberately a third, independent fact from the two other
geography concepts this codebase already has:

- companies.country_code / operating_countries: where the business is
  legally registered / actually operates from (company_geo_profile.py).
- companies.search_scope_level / default_search_radius_km / latitude /
  longitude / city: HOW FAR competitor discovery searches around the
  tenant's own location (company_geo_profile.py).

Neither of those answers "which markets does this tenant want to expand
into or compete in" - a manufacturer based in one country can have real
target buyers in three others; a purely local retailer's target market
may be narrower than its operating country. This module is that third
fact, and it is NEVER inferred: no code path here (or anywhere calling
into it) derives a target market from an uploaded file, the tenant's own
country_code, business_type, industry vertical, or product/service
catalog - every row in company_target_markets exists because a human
explicitly added it through set_tenant_target_markets(), full stop. A
tenant with zero rows here has explicitly configured nothing, and every
caller (discovery's resolve_tenant_geo_scope(), classification's
_in_target_market_scope()) must treat that as "no declared target markets"
- never as a silent fallback to country_code or operating_countries.

Three market_type shapes, matching the migration's own CHECK constraint:

- COUNTRY: a real 2-letter ISO code (country_code set, region_name NULL).
  Reuses company_geo_profile.py's own _normalize_country_codes() verbatim
  - same validation, not reimplemented.
- REGION: free text (region_name set, country_code NULL) - deliberately
  NOT a fixed enum of named regions ("Middle East", "Europe", ...). This
  platform has no authoritative, industry-agnostic region->country
  mapping anywhere, and inventing one would mean guessing which countries
  a human-typed region name actually includes. A REGION entry is real,
  honest evidence for discovery's own search-bias text (a search engine
  can interpret "Middle East" as a real query term) but is intentionally
  NEVER used by competitor_classification.py's country-evidence gate,
  which only trusts an unambiguous ISO country_code match or GLOBAL.
- GLOBAL: "compete everywhere" (both fields NULL) - at most one per
  tenant (DB partial unique index). Deliberately exclusive with every
  other entry: a tenant who wants worldwide reach has nothing more
  specific to also declare, and mixing them is ambiguous (which real
  markets would a mix of "everywhere" plus "also Egypt specifically" even
  mean?) - set_tenant_target_markets() rejects that combination outright
  rather than silently picking one interpretation.

Generic for any industry and any country: no fixed list of countries or
regions, no industry-specific vocabulary anywhere in this module.
"""
from typing import Iterable

from src.market_scraper.company_geo_profile import _normalize_country_codes

MARKET_TYPE_COUNTRY = "COUNTRY"
MARKET_TYPE_REGION = "REGION"
MARKET_TYPE_GLOBAL = "GLOBAL"
VALID_MARKET_TYPES = {MARKET_TYPE_COUNTRY, MARKET_TYPE_REGION, MARKET_TYPE_GLOBAL}

_MAX_REGION_NAME_LEN = 100


def _normalize_region_name(raw: str) -> str:
    """Collapses internal whitespace and trims - the only normalization a
    genuinely free-text, generic field can honestly apply (no casing
    rules that would mangle a real proper name in some other script/
    language, no fixed vocabulary check)."""
    normalized = " ".join((raw or "").split())
    if not normalized:
        raise ValueError("region_name must not be empty for a REGION target market")
    if len(normalized) > _MAX_REGION_NAME_LEN:
        raise ValueError(f"region_name must be at most {_MAX_REGION_NAME_LEN} characters")
    return normalized


def _normalize_target_markets(markets: Iterable[dict]) -> list:
    """
    Validates and normalizes a caller-supplied list of target-market
    entries, each shaped like {"market_type": "COUNTRY"|"REGION"|"GLOBAL",
    "country_code": <2-letter code or None>, "region_name": <text or
    None>}. Raises ValueError (never silently drops/guesses) for:
    - an unknown market_type
    - a COUNTRY entry with no/invalid country_code, or one carrying a
      region_name
    - a REGION entry with no region_name, or one carrying a country_code
    - a GLOBAL entry carrying either field
    - GLOBAL combined with any other entry in the same list (ambiguous -
      see this module's own docstring)
    Deduplicates (same country twice, or the same region name differing
    only in case/whitespace, collapses to one entry) while preserving
    first-occurrence order, same convention as company_geo_profile.py's
    _normalize_country_codes().
    """
    normalized = []
    seen_countries = set()
    seen_regions = set()
    has_global = False

    for entry in markets:
        market_type = (entry or {}).get("market_type")
        if market_type not in VALID_MARKET_TYPES:
            raise ValueError(f"invalid market_type: {market_type!r} (expected one of {sorted(VALID_MARKET_TYPES)})")

        if market_type == MARKET_TYPE_COUNTRY:
            if entry.get("region_name"):
                raise ValueError("a COUNTRY target market must not carry a region_name")
            code = _normalize_country_codes([entry.get("country_code")])[0]
            if code not in seen_countries:
                seen_countries.add(code)
                normalized.append({"market_type": MARKET_TYPE_COUNTRY, "country_code": code, "region_name": None})

        elif market_type == MARKET_TYPE_REGION:
            if entry.get("country_code"):
                raise ValueError("a REGION target market must not carry a country_code")
            region_name = _normalize_region_name(entry.get("region_name"))
            region_key = region_name.casefold()
            if region_key not in seen_regions:
                seen_regions.add(region_key)
                normalized.append({"market_type": MARKET_TYPE_REGION, "country_code": None, "region_name": region_name})

        else:  # MARKET_TYPE_GLOBAL
            if entry.get("country_code") or entry.get("region_name"):
                raise ValueError("a GLOBAL target market must not carry a country_code or region_name")
            has_global = True

    if has_global:
        if normalized:
            raise ValueError(
                "GLOBAL cannot be combined with specific country/region target markets - "
                "choose GLOBAL alone, or specific countries/regions without GLOBAL"
            )
        normalized.append({"market_type": MARKET_TYPE_GLOBAL, "country_code": None, "region_name": None})

    return normalized


def set_tenant_target_markets(conn, tenant_id: str, markets: Iterable[dict]) -> list:
    """
    Replaces the tenant's ENTIRE declared target-market list with exactly
    what the caller supplies - a real PUT/replace semantic (delete every
    existing row, insert the new set), not a partial merge, so removing a
    market the user unchecks actually removes it rather than requiring a
    separate delete call. An empty list is a valid, explicit choice ("no
    target markets declared") and clears any previously-stored rows.

    Raises ValueError for a malformed entry (via _normalize_target_markets())
    or an unknown tenant_id, exactly like set_tenant_search_scope()'s own
    contract.
    """
    normalized = _normalize_target_markets(markets)

    with conn.cursor() as cursor:
        cursor.execute("SELECT 1 FROM companies WHERE tenant_id = %s;", (tenant_id,))
        if cursor.fetchone() is None:
            raise ValueError(f"tenant_id not found: {tenant_id!r}")

        cursor.execute("DELETE FROM company_target_markets WHERE tenant_id = %s;", (tenant_id,))
        if normalized:
            cursor.executemany(
                "INSERT INTO company_target_markets (tenant_id, market_type, country_code, region_name) "
                "VALUES (%s, %s, %s, %s);",
                [
                    (tenant_id, entry["market_type"], entry["country_code"], entry["region_name"])
                    for entry in normalized
                ],
            )
    conn.commit()
    return normalized


def get_tenant_target_markets(conn, tenant_id: str) -> list:
    """Real, currently-declared target markets only - an empty list means
    exactly that (nothing declared yet), never a computed/inferred
    fallback. Sorted for a stable, deterministic response the frontend can
    render without its own re-sorting."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT market_type, country_code, region_name FROM company_target_markets "
            "WHERE tenant_id = %s ORDER BY market_type, country_code, region_name;",
            (tenant_id,),
        )
        return [
            {"market_type": row[0], "country_code": row[1], "region_name": row[2]}
            for row in cursor.fetchall()
        ]


def extract_country_codes(markets: Iterable[dict]) -> list:
    """The COUNTRY-type entries' real ISO codes only - the one shape with
    unambiguous evidence competitor_classification.py's own gate can
    honestly act on. Used by both discovery (search-bias text) and
    classification (region-scope override)."""
    return [entry["country_code"] for entry in markets if entry.get("market_type") == MARKET_TYPE_COUNTRY]


def extract_region_names(markets: Iterable[dict]) -> list:
    """The REGION-type entries' free-text names - discovery-bias evidence
    only (see this module's own docstring for why classification never
    uses these)."""
    return [entry["region_name"] for entry in markets if entry.get("market_type") == MARKET_TYPE_REGION]


def has_global_target_market(markets: Iterable[dict]) -> bool:
    return any(entry.get("market_type") == MARKET_TYPE_GLOBAL for entry in markets)

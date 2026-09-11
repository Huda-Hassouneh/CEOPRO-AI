"""
CEOPRO AI - Tenant search-scope profile (multi-country + proximity radius).

The persistence side of "if a user inputs multiple countries, save it to
the company's profile in the database, and let the discovery algorithm
dynamically decide the search scope from it": companies.operating_countries
already existed for the country allow-list (see sector_detection.py::
resolve_tenant_geo_scope), but nothing previously let a caller update it,
or the new latitude/longitude/default_search_radius_km columns
(20260911000000_add_geo_proximity_and_competitor_scope.sql), together in
one place. This module is that one place - a thin, validated UPDATE, not a
new source of truth.

Every field is optional and independently settable: a caller updates only
what the user actually changed (e.g. just widening the radius from a UI
slider shouldn't require re-sending country/coordinates), matching the
partial-update convention data_access.py::set_source_credentials already
uses elsewhere in this module.
"""
from typing import Iterable, Optional

_VALID_COUNTRY_CODE_LEN = 2

SCOPE_LEVEL_CITY = "CITY"
SCOPE_LEVEL_PROVINCE = "PROVINCE"
SCOPE_LEVEL_COUNTRY = "COUNTRY"
SCOPE_LEVEL_CUSTOM = "CUSTOM"
VALID_SCOPE_LEVELS = {SCOPE_LEVEL_CITY, SCOPE_LEVEL_PROVINCE, SCOPE_LEVEL_COUNTRY, SCOPE_LEVEL_CUSTOM}

# UX fix: "how is a user supposed to guess the exact kilometer distance?" -
# the end user picks one of these named levels (a dropdown/segmented
# control, not a slider with a number), and the backend resolves the real
# radius_km. COUNTRY/CUSTOM are deliberately absent from this dict: COUNTRY
# means no radius filter at all (operating_countries alone decides scope),
# CUSTOM means the caller is supplying its own km (an advanced/API path,
# not a value a typical end user types in).
SCOPE_LEVEL_PRESET_RADIUS_KM = {
    SCOPE_LEVEL_CITY: 25,
    SCOPE_LEVEL_PROVINCE: 150,
}


def _normalize_country_codes(codes: Iterable[str]) -> list:
    """
    Uppercases and de-duplicates while preserving order; rejects anything
    that isn't a 2-letter code outright rather than silently dropping it -
    a caller passing a mistyped code should see an error now, not a
    silently-incomplete operating_countries list later.
    """
    seen = []
    for raw in codes:
        code = (raw or "").strip().upper()
        if len(code) != _VALID_COUNTRY_CODE_LEN or not code.isalpha():
            raise ValueError(f"invalid country code: {raw!r} (expected a 2-letter ISO code)")
        if code not in seen:
            seen.append(code)
    return seen


def set_tenant_search_scope(
    conn,
    tenant_id: str,
    operating_countries: Optional[Iterable[str]] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    city: Optional[str] = None,
    search_scope_level: Optional[str] = None,
    custom_radius_km: Optional[int] = None,
) -> dict:
    """
    Persists whichever of these the caller actually supplies - a field left
    as None here is NOT written as NULL, it's simply left untouched (the
    COALESCE pattern below), so calling this to update only the scope
    level never wipes out a previously-saved country list or location.

    latitude/longitude are validated as real WGS84 coordinates when given
    together (both or neither - a lone latitude with no longitude is a
    caller bug, not a valid partial update, so it's rejected rather than
    silently stored as half a location).

    search_scope_level is the real UX fix: the caller (a dropdown/segmented
    control, never a "type a number of km" field) passes one of CITY/
    PROVINCE/COUNTRY/CUSTOM, and this function - not the end user - resolves
    the actual radius_km:
      - CITY/PROVINCE: resolved from SCOPE_LEVEL_PRESET_RADIUS_KM - a real
        km value is stored, but no human ever typed it.
      - COUNTRY: radius_km is explicitly cleared to NULL - "same target
        region" now means operating_countries alone, no distance filter at
        all (a business's whole country of operation, not a ring around
        one point).
      - CUSTOM: the one escape hatch for an advanced/API caller who
        genuinely wants a specific km figure - custom_radius_km is
        required together with this level, since there's no sensible
        preset to fall back on.
    Omitting search_scope_level entirely leaves both it and the stored
    radius untouched, so a call that's only updating e.g. the coordinates
    doesn't need to know or re-state the tenant's current scope level.
    """
    if (latitude is None) != (longitude is None):
        raise ValueError("latitude and longitude must be provided together")
    if latitude is not None and not (-90.0 <= latitude <= 90.0):
        raise ValueError(f"latitude out of range: {latitude!r}")
    if longitude is not None and not (-180.0 <= longitude <= 180.0):
        raise ValueError(f"longitude out of range: {longitude!r}")
    if search_scope_level is not None and search_scope_level not in VALID_SCOPE_LEVELS:
        raise ValueError(f"invalid search_scope_level: {search_scope_level!r} (expected one of {sorted(VALID_SCOPE_LEVELS)})")
    if search_scope_level == SCOPE_LEVEL_CUSTOM and custom_radius_km is None:
        raise ValueError("custom_radius_km is required when search_scope_level='CUSTOM'")
    if search_scope_level != SCOPE_LEVEL_CUSTOM and custom_radius_km is not None:
        raise ValueError("custom_radius_km is only accepted together with search_scope_level='CUSTOM'")
    if custom_radius_km is not None and custom_radius_km <= 0:
        raise ValueError(f"custom_radius_km must be positive: {custom_radius_km!r}")

    normalized_countries = (
        _normalize_country_codes(operating_countries) if operating_countries is not None else None
    )

    # Resolve the real radius_km server-side - this is the whole point of
    # the fix: an end user never supplies a kilometer number for CITY/
    # PROVINCE/COUNTRY, only for the explicit CUSTOM escape hatch.
    radius_km_to_set = None
    if search_scope_level in SCOPE_LEVEL_PRESET_RADIUS_KM:
        radius_km_to_set = SCOPE_LEVEL_PRESET_RADIUS_KM[search_scope_level]
    elif search_scope_level == SCOPE_LEVEL_CUSTOM:
        radius_km_to_set = custom_radius_km
    # search_scope_level == COUNTRY leaves radius_km_to_set at None below,
    # and the CASE in the UPDATE explicitly clears the stored radius for
    # it rather than leaving a stale CITY/PROVINCE value in place.

    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE companies
            SET operating_countries = COALESCE(%(countries)s, operating_countries),
                latitude = COALESCE(%(lat)s, latitude),
                longitude = COALESCE(%(lon)s, longitude),
                city = COALESCE(%(city)s, city),
                search_scope_level = COALESCE(%(level)s, search_scope_level),
                default_search_radius_km = CASE
                    WHEN %(level)s IS NULL THEN default_search_radius_km
                    WHEN %(level)s = 'COUNTRY' THEN NULL
                    ELSE %(radius)s
                END
            WHERE tenant_id = %(tenant_id)s
            RETURNING operating_countries, latitude, longitude, city, search_scope_level, default_search_radius_km;
            """,
            {
                "countries": normalized_countries, "lat": latitude, "lon": longitude, "city": city,
                "level": search_scope_level, "radius": radius_km_to_set, "tenant_id": tenant_id,
            },
        )
        row = cursor.fetchone()
    if row is None:
        raise ValueError(f"tenant_id not found: {tenant_id!r}")
    conn.commit()

    return {
        "operating_countries": row[0],
        "latitude": row[1],
        "longitude": row[2],
        "city": row[3],
        "search_scope_level": row[4],
        "default_search_radius_km": row[5],
    }


def get_tenant_search_scope(conn, tenant_id: str) -> dict:
    """Real, current values only - no defaults invented here; a tenant that
    hasn't set a location yet gets None for those fields, and the caller
    (proximity ranking, discovery scope resolution) must handle that
    honestly rather than assume a fallback on this module's behalf.
    search_scope_level itself always has a value (DB default 'PROVINCE'
    for a tenant that never explicitly chose one)."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT country_code, operating_countries, latitude, longitude, city,
                   search_scope_level, default_search_radius_km
            FROM companies WHERE tenant_id = %s;
            """,
            (tenant_id,),
        )
        row = cursor.fetchone()
    if row is None:
        raise ValueError(f"tenant_id not found: {tenant_id!r}")
    return {
        "country_code": row[0],
        "operating_countries": row[1],
        "latitude": row[2],
        "longitude": row[3],
        "city": row[4],
        "search_scope_level": row[5],
        "default_search_radius_km": row[6],
    }

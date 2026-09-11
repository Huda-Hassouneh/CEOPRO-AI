"""
CEOPRO AI - Domain-Level Discovery via Google Places Nearby Search.

The location-aware half of domain-level discovery (the other half is
web_product_discovery.py::discover_industry_candidates(), the Custom
Search-based path): given the tenant's own coordinates and a real
industry keyword, finds real nearby businesses in that industry via the
official Google Places API - never a scrape of Google Maps itself.

Two-step, same pattern spiders/google_places.py already uses for a
different purpose (finding reviews for an already-known competitor):
1. Nearby Search (one call) - location + radius + keyword, returns a page
   of real place_ids with name/geometry, no website field.
2. Place Details (one call per result) - the only way to get a business's
   real website URL; a result with no website field is skipped rather
   than guessed, since this module's own identity model requires a real,
   resolvable domain (matching discovery.py::compute_website_identity_key()).

Honest, real limit: Google's Nearby Search radius parameter caps at 50,000
meters (50km) - a hard API limit, not a design choice. A tenant whose
resolved search radius (company_geo_profile.py's PROVINCE preset is
150km) exceeds that gets silently clamped to the API max rather than
erroring - the caller still gets real, useful nearby results, just not
literally the full requested radius; this is flagged here, not hidden.
"""
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional

from src.market_scraper.discovery import CandidateSource

logger = logging.getLogger("CEOPRO_AI_PLACES_NEARBY_DISCOVERY")

_NEARBY_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
_FETCH_TIMEOUT = 15

# Google's own hard cap for the Nearby Search `radius` parameter - passing
# a larger value is a documented API error, not a soft limit.
MAX_NEARBY_SEARCH_RADIUS_KM = 50


def _get(url: str, params: dict) -> Optional[dict]:
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": "CEOPRO-MarketResearchBot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception as e:  # noqa: BLE001 - any failure here means "no data", not a crash
        logger.warning("Google Places request failed: %s", e)
        return None


def _fetch_details(place_id: str, api_key: str) -> Optional[dict]:
    payload = _get(_DETAILS_URL, {
        "place_id": place_id, "fields": "website,geometry,formatted_address", "key": api_key,
    })
    if not payload or "result" not in payload:
        return None
    return payload["result"]


def discover_nearby_places(
    latitude: float, longitude: float, keyword: str, radius_km: float,
    api_key: Optional[str] = None, max_results: int = 20,
) -> List[CandidateSource]:
    """
    Real Google Places Nearby Search call around (latitude, longitude) for
    `keyword` (a real industry label, e.g. sector_detection.py::
    VERTICAL_INDUSTRY_LABELS' "electronics store") within radius_km
    (clamped to MAX_NEARBY_SEARCH_RADIUS_KM - see module docstring).

    Never fabricates a result: a missing api_key, an API error, or
    genuinely no nearby matches all return [] - the same honest-
    degradation contract every other discovery source in this codebase
    uses. A result missing a real website (common - many small local
    businesses have none) is skipped, not guessed at.

    Returns CandidateSource records carrying REAL coordinates (this
    result's own geometry.location, not the search center) - this is
    what lets classify_competitor() compute a real, specific distance_km
    for each one rather than reusing the search center for every result.
    """
    if api_key is None:
        logger.info("no Google Places API key configured - nearby discovery skipped.")
        return []

    effective_radius_km = min(radius_km, MAX_NEARBY_SEARCH_RADIUS_KM)
    if radius_km > MAX_NEARBY_SEARCH_RADIUS_KM:
        logger.info(
            "requested radius_km=%s exceeds Google Places' %skm Nearby Search cap - clamped.",
            radius_km, MAX_NEARBY_SEARCH_RADIUS_KM,
        )

    payload = _get(_NEARBY_SEARCH_URL, {
        "location": f"{latitude},{longitude}",
        "radius": int(effective_radius_km * 1000),
        "keyword": keyword,
        "key": api_key,
    })
    if not payload:
        return []
    if payload.get("status") not in ("OK", "ZERO_RESULTS"):
        logger.warning("Places Nearby Search returned status=%s for keyword=%r", payload.get("status"), keyword)
        return []

    candidates = []
    for result in (payload.get("results") or [])[:max_results]:
        place_id = result.get("place_id")
        name = result.get("name")
        if not place_id or not name:
            continue
        details = _fetch_details(place_id, api_key)
        website = details.get("website") if details else None
        if not website:
            continue  # no real, resolvable domain to register - never guessed
        location = (details or {}).get("geometry", {}).get("location") or result.get("geometry", {}).get("location") or {}
        candidates.append(CandidateSource(
            product_name=keyword, url=website, title=name,
            latitude=location.get("lat"), longitude=location.get("lng"),
            city=(details or {}).get("formatted_address"),
        ))
    return candidates

"""
CEOPRO AI - Competitor Discovery From Scratch via Google Places (Text Search).

Closes the real gap the user identified: everything else in this module
(direct_search.py, discovery.py) finds MORE data about a competitor once
you already know who they are - it never answers "who even IS my
competitor" for a tenant with zero seed data. This module is that answer,
using the one official, free-tier, self-serve API that actually supports
category/location discovery: Google Places API's Text Search endpoint
(https://maps.googleapis.com/maps/api/place/textsearch/json).

This is a genuinely different Places API call than
spiders/google_places.py's GooglePlacesSpider - that spider takes an
ALREADY-KNOWN competitor name and fetches their reviews (Find Place ->
Place Details). This module takes a PRODUCT NAME OR INDUSTRY plus a
region and returns a list of real, previously-unknown local businesses
matching it - the actual "seed creator" step. The two are complementary,
not duplicates: this module's output (a business name + website) is
exactly what direct_search.py/market_source.py need to then analyze that
business for real, and what GooglePlacesSpider needs to then fetch that
business's real reviews.

Setup this needs (free, self-serve, no lengthy app review unlike Meta's
Graph API - a real Google Cloud project with Places API enabled and an
API key with monthly free-tier quota):
    export GOOGLE_PLACES_API_KEY=<your key>

Never fabricates a result: a missing key, an API error, or zero real
matches all return an empty list, not a guessed business name.
"""
import json
import logging
import os
import urllib.parse
import urllib.request
from typing import List, Optional

logger = logging.getLogger("CEOPRO_AI_PLACES_DISCOVERY")

_TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
_FETCH_TIMEOUT = 15

# Google's own documented cap: Text Search returns up to 20 results per
# page (paginating further costs another quota-consuming request per
# page) - capped here to the first page only, since a handful of real
# local competitors is the actual goal, not exhaustively enumerating
# every business Google knows about.
_MAX_RESULTS = 20


def _get(url: str, params: dict) -> Optional[dict]:
    """Real HTTP GET against the Places API, decoded as JSON. Returns None
    on any failure (network error, non-2xx, unparseable body) - never a
    fabricated stand-in for a real response."""
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": "CEOPRO-MarketResearchBot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception as e:  # noqa: BLE001 - any failure here means "no data", not a crash
        logger.warning("Places API request to %s failed: %s", url, e)
        return None


def discover_businesses(
    query: str, region: Optional[str] = None, api_key: Optional[str] = None, max_results: int = 10,
) -> List[dict]:
    """
    The real "seed creator": searches Google Places for `query` (a product
    name, e.g. "handmade shoes", or an industry/category), optionally
    scoped to `region` (a free-text location string, e.g. "Amman, Jordan" -
    Places' Text Search accepts location as part of the query text itself,
    no separate geocoding call needed), and returns real local businesses
    Google's own index has for it.

    Each result: {"name", "address", "place_id", "website", "rating",
    "user_ratings_total"}. `website` requires a second real Place Details
    call per result (Text Search itself doesn't return it) - capped at
    `max_results` specifically to bound that fan-out, since each one is a
    real, quota-consuming API call.

    Returns [] (never a guess) when GOOGLE_PLACES_API_KEY isn't set, the
    API call fails, or there are genuinely no matches.
    """
    api_key = api_key or os.getenv("GOOGLE_PLACES_API_KEY")
    if not api_key:
        logger.info("GOOGLE_PLACES_API_KEY not set - competitor discovery via Places API skipped.")
        return []

    search_text = f"{query} in {region}" if region else query
    search_result = _get(_TEXT_SEARCH_URL, {"query": search_text, "key": api_key})
    if not search_result or search_result.get("status") not in ("OK", "ZERO_RESULTS"):
        logger.warning(
            "Places Text Search for %r returned status=%s", search_text,
            search_result.get("status") if search_result else "no response",
        )
        return []

    candidates = (search_result.get("results") or [])[:max_results]
    businesses = []
    for candidate in candidates:
        place_id = candidate.get("place_id")
        name = candidate.get("name")
        if not place_id or not name:
            continue

        website = None
        details = _get(
            _DETAILS_URL, {"place_id": place_id, "fields": "website", "key": api_key},
        )
        if details and details.get("status") == "OK":
            website = (details.get("result") or {}).get("website")

        businesses.append({
            "name": name,
            "address": candidate.get("formatted_address"),
            "place_id": place_id,
            "website": website,
            "rating": candidate.get("rating"),
            "user_ratings_total": candidate.get("user_ratings_total"),
        })

    return businesses

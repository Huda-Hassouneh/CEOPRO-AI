"""Google Places API (New): Nearby Search by type around the company plus a
Text Search per keyword. Needs GOOGLE_PLACES_API_KEY (Places API (New)
enabled). Each call returns at most 20 places, so the area is searched as
the centre plus a ring of tiles when the radius is large."""
import logging
import math
import os

import httpx

from src.market_scraper.market_discovery import industries
from src.market_scraper.market_discovery.http import request_json
from src.market_scraper.market_discovery.models import Candidate, DiscoveryQuery, ProviderResult

logger = logging.getLogger("APEX_MARKET_DISCOVERY")
NAME = "google_places"
NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
TEXT_URL = "https://places.googleapis.com/v1/places:searchText"
FIELDS = ",".join(f"places.{f}" for f in (
    "id", "displayName", "formattedAddress", "location", "types", "websiteUri", "nationalPhoneNumber",
    "rating", "userRatingCount", "priceLevel", "googleMapsUri", "businessStatus"))
PRICE_LEVELS = {"PRICE_LEVEL_FREE": 0, "PRICE_LEVEL_INEXPENSIVE": 1, "PRICE_LEVEL_MODERATE": 2,
                "PRICE_LEVEL_EXPENSIVE": 3, "PRICE_LEVEL_VERY_EXPENSIVE": 4}
MAX_RADIUS_M = 50000
MAX_CALLS = int(os.getenv("GOOGLE_PLACES_MAX_CALLS_PER_RUN", "12"))


def _key():
    return os.getenv("GOOGLE_PLACES_API_KEY") or os.getenv("GOOGLE_MAPS_API_KEY")


def available():
    return (True, None) if _key() else (False, "not_configured")


def tiles(lat: float, lon: float, radius_km: float):
    """(lat, lon, radius_m) circles covering the area: one circle up to 3 km,
    otherwise the centre and six neighbours at half the radius."""
    if radius_km <= 3:
        return [(lat, lon, int(radius_km * 1000))]
    sub = radius_km / 2
    out = [(lat, lon, int(min(sub, 50) * 1000))]
    for i in range(6):
        angle = math.radians(60 * i)
        dlat = (sub * math.cos(angle)) / 111.0
        dlon = (sub * math.sin(angle)) / (111.0 * max(math.cos(math.radians(lat)), 0.2))
        out.append((lat + dlat, lon + dlon, int(min(sub, 50) * 1000)))
    return out


def _candidate(place: dict, query: DiscoveryQuery):
    name = ((place.get("displayName") or {}).get("text") or "").strip()
    if not name or place.get("businessStatus") == "CLOSED_PERMANENTLY":
        return None
    location = place.get("location") or {}
    types = place.get("types") or []
    return Candidate(
        name=name, source=NAME, source_ref=place.get("id"),
        source_url=place.get("googleMapsUri"),
        name_ar=name if any("؀" <= ch <= "ۿ" for ch in name) else None,
        website=place.get("websiteUri"), phone=place.get("nationalPhoneNumber"),
        address=place.get("formattedAddress"), city=query.city, country_code=query.country_code,
        latitude=location.get("latitude"), longitude=location.get("longitude"),
        categories=types[:8], industry_key=industries.classify_google_types(types),
        rating=place.get("rating"), review_count=place.get("userRatingCount"),
        price_level=PRICE_LEVELS.get(place.get("priceLevel")),
        raw={"types": types[:10], "businessStatus": place.get("businessStatus")},
    )


def search(query: DiscoveryQuery) -> ProviderResult:
    ok, reason = available()
    if not ok:
        return ProviderResult(NAME, "skipped", reason=reason)
    headers = {"X-Goog-Api-Key": _key(), "X-Goog-FieldMask": FIELDS, "Content-Type": "application/json"}
    language = "ar" if query.language == "ar" else "en"
    calls, found, failures = [], {}, 0
    if query.has_location and query.google_types:
        for lat, lon, radius in tiles(query.latitude, query.longitude, query.radius_km):
            calls.append((NEARBY_URL, {
                "includedTypes": list(query.google_types)[:5], "maxResultCount": 20, "languageCode": language,
                "locationRestriction": {"circle": {"center": {"latitude": lat, "longitude": lon}, "radius": float(min(radius, MAX_RADIUS_M))}},
            }))
    for keyword in query.keywords[:4]:
        body = {"textQuery": keyword if query.has_location or not query.city else f"{keyword} {query.city}",
                "pageSize": 20, "languageCode": language}
        if query.has_location:
            body["locationBias"] = {"circle": {"center": {"latitude": query.latitude, "longitude": query.longitude},
                                               "radius": float(min(query.radius_km * 1000, MAX_RADIUS_M))}}
        if query.country_code:
            body["regionCode"] = query.country_code
        calls.append((TEXT_URL, body))
    calls = calls[:MAX_CALLS]
    for url, body in calls:
        try:
            payload = request_json("POST", url, json_body=body, headers=headers, timeout=20, cache_key_extra="places-v1")
        except (httpx.HTTPError, ValueError) as exc:
            failures += 1
            logger.warning("Google Places call failed: %s", exc)
            continue
        for place in payload.get("places") or []:
            candidate = _candidate(place, query)
            if candidate and candidate.source_ref not in found:
                found[candidate.source_ref] = candidate
    if failures and failures == len(calls):
        return ProviderResult(NAME, "failed", reason="unreachable", requests=len(calls))
    return ProviderResult(NAME, "ok", list(found.values()), requests=len(calls))

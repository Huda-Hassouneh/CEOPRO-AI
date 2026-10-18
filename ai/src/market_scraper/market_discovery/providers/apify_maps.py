"""Apify's Google Maps scraper actor (compass/crawler-google-places) for
accounts that prefer it to the Places API. Needs APIFY_API_TOKEN (the
older name APIFY_TOKEN still works); the actor's own usage is billed to
that Apify account. The token travels in the Authorization header, never
in the URL, so it can't reach logs, error text or cache keys."""
import logging
import os

import httpx

from src.market_scraper.market_discovery import industries
from src.market_scraper.market_discovery.http import request_json
from src.market_scraper.market_discovery.models import Candidate, DiscoveryQuery, ProviderResult

logger = logging.getLogger("APEX_MARKET_DISCOVERY")
NAME = "apify_google_maps"
ACTOR = os.getenv("APIFY_MAPS_ACTOR", "compass~crawler-google-places")
RUN_URL = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
MAX_PLACES = int(os.getenv("APIFY_MAX_PLACES_PER_SEARCH", "40"))


def _token():
    return os.getenv("APIFY_API_TOKEN") or os.getenv("APIFY_TOKEN")  # APIFY_TOKEN: the older name


def available():
    return (True, None) if _token() else (False, "not_configured")


def parse(items, query: DiscoveryQuery):
    out = []
    for item in items or []:
        name = (item.get("title") or "").strip()
        if not name or item.get("permanentlyClosed"):
            continue
        location = item.get("location") or {}
        categories = [c for c in (item.get("categories") or [item.get("categoryName")]) if c]
        ref = item.get("placeId") or item.get("cid") or item.get("url")
        if not ref:
            continue
        out.append(Candidate(
            name=name, source=NAME, source_ref=str(ref), source_url=item.get("url"),
            website=item.get("website"), phone=item.get("phone"), address=item.get("address"),
            city=item.get("city") or query.city, country_code=item.get("countryCode") or query.country_code,
            latitude=location.get("lat"), longitude=location.get("lng"), categories=categories[:8],
            industry_key=industries.classify_google_types([c.lower().replace(" ", "_") for c in categories]),
            rating=item.get("totalScore"), review_count=item.get("reviewsCount"),
            raw={"categoryName": item.get("categoryName")},
        ))
    return out


def search(query: DiscoveryQuery) -> ProviderResult:
    ok, reason = available()
    if not ok:
        return ProviderResult(NAME, "skipped", reason=reason)
    body = {"searchStringsArray": query.keywords[:3], "maxCrawledPlacesPerSearch": MAX_PLACES,
            "language": "ar" if query.language == "ar" else "en", "skipClosedPlaces": True}
    if query.has_location:
        body["customGeolocation"] = {"type": "Point", "coordinates": [query.longitude, query.latitude],
                                     "radiusKm": max(1, round(query.radius_km))}
    elif query.city:
        body["locationQuery"] = query.city
    else:
        return ProviderResult(NAME, "skipped", reason="no_location")
    try:
        items = request_json("POST", RUN_URL.format(actor=ACTOR), json_body=body,
                             headers={"Authorization": f"Bearer {_token()}"}, timeout=180)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        logger.warning("Apify run failed: HTTP %s", status)  # not str(exc): it names the URL
        reason = "auth_failed" if status in (401, 403) else "unreachable"
        return ProviderResult(NAME, "failed", reason=reason, requests=1)
    except httpx.TimeoutException:
        logger.warning("Apify run timed out")
        return ProviderResult(NAME, "failed", reason="timeout", requests=1)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Apify run failed: %s", type(exc).__name__)
        return ProviderResult(NAME, "failed", reason="unreachable", requests=1)
    return ProviderResult(NAME, "ok", parse(items, query), requests=1)

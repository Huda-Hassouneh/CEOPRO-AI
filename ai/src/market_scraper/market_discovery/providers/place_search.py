"""Keyless place search by words, not map tags: "<keyword> <city>".

Complements the Overpass tag search (osm.py) in three cases it can't cover:
the company gave a city but no map pin, its industry has no map tags in
industries.py (professional services, online shops, anything new), or every
Overpass server is busy. Both services search OpenStreetMap data
(c) OpenStreetMap contributors, ODbL:

- Nominatim (nominatim.openstreetmap.org): its usage policy allows light
  use - at most one request a second, an identifying User-Agent, results
  cached (http.py keeps them for a day). A run sends at most MAX_QUERIES.
- Photon (photon.komoot.io): used for any query Nominatim couldn't answer.

NOMINATIM_URL / PHOTON_URL point at self-hosted servers for heavier use;
DISCOVERY_DISABLE_PLACE_SEARCH=true turns this source off.
"""
import logging
import math
import os
import time
from typing import List, Optional

import httpx

from src.market_scraper.market_discovery import industries
from src.market_scraper.market_discovery.http import request_json
from src.market_scraper.market_discovery.models import Candidate, DiscoveryQuery, ProviderResult

logger = logging.getLogger("KEEL_MARKET_DISCOVERY")
NAME = "place_search"
NOMINATIM_URL = os.getenv("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
PHOTON_URL = os.getenv("PHOTON_URL", "https://photon.komoot.io/api/")
MAX_QUERIES = int(os.getenv("PLACE_SEARCH_MAX_QUERIES", "3"))
PER_QUERY = 40
NOMINATIM_INTERVAL_SECONDS = 1.1
# Map feature classes that are businesses (not roads, towns or rivers).
BUSINESS_CLASSES = {"amenity", "shop", "tourism", "healthcare", "office", "craft", "leisure", "club"}
_NOT_BUSINESS_TYPES = {"parking", "bench", "toilets", "atm", "bus_station", "fuel", "place_of_worship", "school",
                       "townhall", "post_box", "drinking_water", "waste_basket", "vending_machine", "bicycle_parking"}


def available():
    if os.getenv("DISCOVERY_DISABLE_PLACE_SEARCH", "").lower() in ("1", "true", "yes"):
        return False, "disabled"
    return True, None


def _viewbox(query: DiscoveryQuery) -> Optional[str]:
    if not query.has_location:
        return None
    d_lat = query.radius_km / 111.0
    d_lon = query.radius_km / (111.0 * max(0.2, abs(math.cos(math.radians(query.latitude)))))
    return f"{query.longitude - d_lon:.5f},{query.latitude + d_lat:.5f},{query.longitude + d_lon:.5f},{query.latitude - d_lat:.5f}"


def _texts(query: DiscoveryQuery) -> List[str]:
    place = query.city or ""
    seen, out = set(), []
    for keyword in query.keywords:
        text = f"{keyword} {place}".strip()
        if text.lower() not in seen:
            seen.add(text.lower())
            out.append(text)
    return out[:MAX_QUERIES]


def _is_business(feature_class: Optional[str], feature_type: Optional[str]) -> bool:
    return feature_class in BUSINESS_CLASSES and feature_type not in _NOT_BUSINESS_TYPES


def parse_nominatim(results, query: DiscoveryQuery) -> List[Candidate]:
    out = []
    for item in results or []:
        feature_class, feature_type = item.get("category") or item.get("class"), item.get("type")
        if not _is_business(feature_class, feature_type):
            continue
        names = item.get("namedetails") or {}
        name = (names.get("name:en") or item.get("name") or names.get("name") or "").strip()
        if not name:
            continue
        extra = item.get("extratags") or {}
        address = item.get("address") or {}
        ref = f"{item.get('osm_type')}/{item.get('osm_id')}"
        street = " ".join(p for p in (address.get("house_number"), address.get("road")) if p)
        out.append(Candidate(
            name=name, name_ar=names.get("name:ar"), source="nominatim", source_ref=ref,
            source_url=f"https://www.openstreetmap.org/{ref}",
            website=extra.get("website") or extra.get("contact:website") or extra.get("url"),
            phone=extra.get("phone") or extra.get("contact:phone"),
            address=", ".join(p for p in (street, address.get("suburb") or address.get("neighbourhood")) if p) or None,
            city=address.get("city") or address.get("town") or query.city, country_code=query.country_code,
            latitude=float(item["lat"]) if item.get("lat") else None, longitude=float(item["lon"]) if item.get("lon") else None,
            categories=[f"{feature_class}={feature_type}"],
            industry_key=industries.classify_tags({feature_class: feature_type}),
            raw={"display_name": (item.get("display_name") or "")[:200]},
        ))
    return out


def parse_photon(payload, query: DiscoveryQuery) -> List[Candidate]:
    out = []
    for feature in (payload or {}).get("features") or []:
        props = feature.get("properties") or {}
        feature_class, feature_type = props.get("osm_key"), props.get("osm_value")
        if not _is_business(feature_class, feature_type) or not props.get("name"):
            continue
        lon, lat = ((feature.get("geometry") or {}).get("coordinates") or [None, None])[:2]
        osm_type = {"N": "node", "W": "way", "R": "relation"}.get(props.get("osm_type"), props.get("osm_type"))
        ref = f"{osm_type}/{props.get('osm_id')}"
        street = " ".join(p for p in (props.get("housenumber"), props.get("street")) if p)
        out.append(Candidate(
            name=props["name"].strip(), source="photon", source_ref=ref, source_url=f"https://www.openstreetmap.org/{ref}",
            address=", ".join(p for p in (street, props.get("district")) if p) or None,
            city=props.get("city") or query.city, country_code=query.country_code, latitude=lat, longitude=lon,
            categories=[f"{feature_class}={feature_type}"], industry_key=industries.classify_tags({feature_class: feature_type}),
        ))
    return out


def _nominatim(text: str, query: DiscoveryQuery):
    params = {"q": text, "format": "jsonv2", "limit": PER_QUERY, "extratags": 1, "namedetails": 1, "addressdetails": 1,
              "accept-language": "ar,en" if query.language == "ar" else "en,ar"}
    if query.country_code:
        params["countrycodes"] = query.country_code.lower()
    viewbox = _viewbox(query)
    if viewbox:
        params["viewbox"], params["bounded"] = viewbox, 1
    return request_json("GET", NOMINATIM_URL, params=params, timeout=15, cache_key_extra="place-search")


def _photon(text: str, query: DiscoveryQuery):
    params = {"q": text, "limit": PER_QUERY}
    if query.has_location:
        params["lat"], params["lon"] = round(query.latitude, 5), round(query.longitude, 5)
    if query.language in ("en", "de", "fr"):
        params["lang"] = query.language
    return request_json("GET", PHOTON_URL, params=params, timeout=15, cache_key_extra="place-search")


def search(query: DiscoveryQuery, sleep=time.sleep) -> ProviderResult:
    ok, reason = available()
    if not ok:
        return ProviderResult(NAME, "skipped", reason=reason)
    if not query.has_location and not query.city:
        return ProviderResult(NAME, "skipped", reason="no_location")
    found, requests, answered = {}, 0, 0
    for index, text in enumerate(_texts(query)):
        if index:
            sleep(NOMINATIM_INTERVAL_SECONDS)  # Nominatim's one-request-a-second rule
        candidates = None
        for fetch, parse in ((_nominatim, parse_nominatim), (_photon, parse_photon)):
            requests += 1
            try:
                candidates = parse(fetch(text, query), query)
                break
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("place search %s failed for one query: %s", fetch.__name__, type(exc).__name__)
        if candidates is None:
            continue
        answered += 1
        for candidate in candidates:
            found.setdefault(candidate.source_ref, candidate)
    if not answered:
        return ProviderResult(NAME, "failed", reason="unreachable", requests=requests)
    return ProviderResult(NAME, "ok", list(found.values()), requests=requests)

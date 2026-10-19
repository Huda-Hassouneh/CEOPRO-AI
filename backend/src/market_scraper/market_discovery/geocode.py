"""City -> coordinates, for companies that gave a city but no map pin:
the built-in city table (cities.py) first, then Google Geocoding when a key
is configured, OpenStreetMap Nominatim and Photon (keyless, cached a day)."""
import logging
import os
from typing import Optional, Tuple

import httpx

from src.market_scraper.market_discovery import cities
from src.market_scraper.market_discovery.http import request_json

logger = logging.getLogger("APEX_MARKET_DISCOVERY")
NOMINATIM_URL = os.getenv("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
PHOTON_URL = os.getenv("PHOTON_URL", "https://photon.komoot.io/api/")
GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"


def _google(city, country_code):
    key = os.getenv("GOOGLE_PLACES_API_KEY") or os.getenv("GOOGLE_MAPS_API_KEY")
    if not key:
        return None
    params = {"address": city, "key": key}
    if country_code:
        params["components"] = f"country:{country_code}"
    results = request_json("GET", GOOGLE_GEOCODE_URL, params=params, timeout=10, cache_key_extra="geocode").get("results") or []
    location = results[0]["geometry"]["location"] if results else None
    return (float(location["lat"]), float(location["lng"])) if location else None


def _nominatim(city, country_code):
    params = {"q": city, "format": "json", "limit": 1}
    if country_code:
        params["countrycodes"] = country_code.lower()
    results = request_json("GET", NOMINATIM_URL, params=params, timeout=10)
    return (float(results[0]["lat"]), float(results[0]["lon"])) if results else None


def _photon(city, country_code):
    features = request_json("GET", PHOTON_URL, params={"q": city, "limit": 5}, timeout=10).get("features") or []
    for feature in features:
        props = feature.get("properties") or {}
        if country_code and (props.get("countrycode") or "").upper() != country_code.upper():
            continue
        lon, lat = (feature.get("geometry") or {}).get("coordinates") or (None, None)
        if lat is not None:
            return float(lat), float(lon)
    return None


def geocode_city(city: Optional[str], country_code: Optional[str]) -> Optional[Tuple[float, float]]:
    """City -> its centre. The built-in table answers for the region's main
    cities with no network at all; otherwise each geocoder is tried in turn,
    one failing never stopping the next."""
    if not city:
        return None
    point = cities.lookup(city, country_code)
    if point:
        return point
    for name, finder in (("google", _google), ("nominatim", _nominatim), ("photon", _photon)):
        try:
            point = finder(city, country_code)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            logger.warning("geocoding %r with %s failed: %s", city, name, type(exc).__name__)
            continue
        if point:
            return point
    return None

"""OpenStreetMap via the Overpass API: keyless, open data (ODbL), good
coverage of shops, restaurants, hotels and pharmacies in most cities.

Finds every mapped place within the radius whose tags match the company's
industry. Attribution: data (c) OpenStreetMap contributors."""
import logging
import math
import os
import re

import httpx

from src.market_scraper.market_discovery import industries
from src.market_scraper.market_discovery.matching import distance_km
from src.market_scraper.market_discovery.http import request_json
from src.market_scraper.market_discovery.models import Candidate, DiscoveryQuery, ProviderResult

logger = logging.getLogger("APEX_MARKET_DISCOVERY")
NAME = "openstreetmap"
# Public Overpass servers, tried in order: the main one is often busy (429)
# or times out (504), and one busy server must not leave a company with no
# map results. OVERPASS_API_URL (one) or OVERPASS_API_URLS (comma list)
# replaces the list, e.g. with a self-hosted server.
DEFAULT_OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)


def overpass_urls():
    configured = os.getenv("OVERPASS_API_URLS") or os.getenv("OVERPASS_API_URL") or ""
    urls = [u.strip() for u in configured.split(",") if u.strip()]
    return urls or list(DEFAULT_OVERPASS_URLS)
MAX_RADIUS_KM = 30.0


def available():
    if os.getenv("DISCOVERY_DISABLE_OSM", "").lower() in ("1", "true", "yes"):
        return False, "disabled"
    return True, None


_BUSINESS_KEYS = ("shop", "amenity", "office", "craft")


# Words that say nothing about what a business does, in a description.
_GENERAL_WORDS = {"company", "shop", "store", "online", "services", "service", "center", "centre", "office", "and",
                  "the", "for", "group", "management", "solutions", "trading", "international", "general",
                  "national", "global", "متجر", "محل", "مكتب", "شركة", "شركه", "مؤسسة", "مؤسسه", "مركز", "خدمات"}


def _stem(word: str) -> str:
    """Arabic: drop the article/prefixed preposition and common endings, so
    عقاري / العقارية / للعقارات all become عقار. English: drop a plural s."""
    if re.search(r"[\u0600-\u06ff]", word):
        word = re.sub(r"^(?:وال|بال|فال|كال|لل|ال)", "", word)
        word = re.sub(r"(?:يات|ية|ات|ين|ون|ي|ه|ة)$", "", word)
        return word if len(word) >= 3 else ""
    return word[:-1] if len(word) > 4 and word.lower().endswith("s") else word


def _name_pattern(keywords, by_word: bool = False) -> str:
    """Business names containing the industry's words ("حلويات", "sweets").
    by_word: also each meaningful word of a phrase, by its stem - for a
    business type described in the owner's own words."""
    words = []
    for keyword in keywords or []:
        word = re.sub(r"[^\w\s\u0600-\u06ff]", "", keyword or "").strip()
        if len(word) >= 3 and word.lower() not in ("store", "shop", "متجر", "online store"):
            words.append(word)
        if by_word and " " in word:
            # Arabic stems from 3 letters; Latin words from 6 ("software",
            # "estate"), so "real" or "agent" alone never match any name.
            words += [stem for part in word.split() if part.lower() not in _GENERAL_WORDS
                      for stem in [_stem(part)] if len(stem) >= (3 if re.search(r"[\u0600-\u06ff]", stem) else 6)]
    return "|".join(dict.fromkeys(words))[:300]


def _bbox(query: DiscoveryQuery) -> str:
    """The square around the radius. Overpass answers a bounding box from
    its spatial index; an (around:...) filter over a whole city measures
    every candidate's distance and timed out on the public servers for
    Amman. Places in the box's corners are dropped in parse()."""
    radius = min(query.radius_km, MAX_RADIUS_KM)
    dlat = radius / 111.32
    dlon = radius / (111.32 * max(math.cos(math.radians(query.latitude)), 0.01))
    return f"{query.latitude - dlat:.6f},{query.longitude - dlon:.6f},{query.latitude + dlat:.6f},{query.longitude + dlon:.6f}"


def build_query(query: DiscoveryQuery, with_names: bool = True) -> str:
    """Businesses of the industry's map types within the radius, plus
    businesses whose name contains the industry's words - which also covers
    industries with no map type of their own. with_names=False is the
    lighter retry when a server gives up on the full search."""
    parts = []
    for key, value in query.osm_tags:
        parts.append(f'nwr["{key}"="{value}"]["name"];')
    pattern = _name_pattern(query.keywords, by_word=query.industry_key == industries.CUSTOM) if with_names else ""
    if pattern:
        for key in _BUSINESS_KEYS:
            parts.append(f'nwr["{key}"]["name"~"{pattern}",i];')
    return f"[out:json][timeout:60][bbox:{_bbox(query)}];({''.join(parts)});out center tags {query.max_results};"


def _address(tags: dict):
    street = " ".join(p for p in (tags.get("addr:housenumber"), tags.get("addr:street")) if p)
    parts = [p for p in (street, tags.get("addr:suburb") or tags.get("addr:district"), tags.get("addr:city")) if p]
    return ", ".join(parts) or None


def parse(payload: dict, query: DiscoveryQuery):
    pattern = _name_pattern(query.keywords, by_word=query.industry_key == industries.CUSTOM)
    out = []
    for element in payload.get("elements") or []:
        tags = element.get("tags") or {}
        name = (tags.get("name") or tags.get("name:en") or tags.get("name:ar") or "").strip()
        if not name:
            continue
        lat = element.get("lat") or (element.get("center") or {}).get("lat")
        lon = element.get("lon") or (element.get("center") or {}).get("lon")
        away = distance_km(query.latitude, query.longitude, lat, lon)
        if away is not None and away > min(query.radius_km, MAX_RADIUS_KM):
            continue  # in the search box's corner, outside the radius
        ref = f"{element.get('type')}/{element.get('id')}"
        categories = [f"{k}={tags[k]}" for k in ("amenity", "shop", "tourism", "healthcare", "office", "leisure", "cuisine") if tags.get(k)]
        names = " ".join(v for k, v in tags.items() if k == "name" or k.startswith("name:"))
        name_match = bool(pattern and re.search(pattern, names, re.IGNORECASE))
        out.append(Candidate(
            name=tags.get("name:en") or name,
            name_ar=tags.get("name:ar") or (name if any("؀" <= ch <= "ۿ" for ch in name) else None),
            source=NAME, source_ref=ref,
            source_url=f"https://www.openstreetmap.org/{ref}",
            website=tags.get("website") or tags.get("contact:website") or tags.get("url"),
            phone=tags.get("phone") or tags.get("contact:phone"),
            address=_address(tags), city=tags.get("addr:city") or query.city,
            country_code=query.country_code,
            latitude=lat, longitude=lon, categories=categories,
            industry_key=industries.classify_tags(tags),
            raw={**{k: tags[k] for k in list(tags)[:25]}, "name_match": name_match},
        ))
    return out


def search(query: DiscoveryQuery) -> ProviderResult:
    ok, reason = available()
    if not ok:
        return ProviderResult(NAME, "skipped", reason=reason)
    if not query.has_location:
        return ProviderResult(NAME, "skipped", reason="no_location")
    if not query.osm_tags and not _name_pattern(query.keywords):
        return ProviderResult(NAME, "skipped", reason="industry_not_mapped")
    requests = 0
    queries = [build_query(query)]
    if query.osm_tags and _name_pattern(query.keywords):
        queries.append(build_query(query, with_names=False))
    for text in queries:
        for url in overpass_urls():
            requests += 1
            try:
                payload = request_json("POST", url, data={"data": text}, timeout=75, cache_if=_answered)
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("Overpass server %s failed: %s", url, type(exc).__name__)
                continue
            if not _answered(payload):
                logger.warning("Overpass server %s gave up: %s", url, str(payload.get("remark"))[:120])
                continue
            return ProviderResult(NAME, "ok", parse(payload, query), requests=requests)
    return ProviderResult(NAME, "failed", reason="unreachable", requests=requests)


def _answered(payload) -> bool:
    """A server that ran out of time or memory answers 200 with a remark and
    no data - that is not an answer (and must not be cached as one)."""
    remark = str((payload or {}).get("remark") or "").lower()
    return bool(payload.get("elements")) or not ("error" in remark or "timed out" in remark or "out of memory" in remark)

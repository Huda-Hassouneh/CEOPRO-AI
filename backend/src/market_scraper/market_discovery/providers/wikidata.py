"""Wikidata: the open company database (CC0, keyless).

Finds the companies and brands people search for in the company's country
by industry words - national chains, well-known brands and established
businesses that a map search around one address misses - with the facts
Wikidata records about them: official website, social accounts, industry
and founding year. Each result links to its Wikidata page as the source.

Two calls per keyword: a full-text search limited to entities in the
country (haswbstatement:P17), then the entities themselves. Only
organisations are kept: an entity must not be a person or a place and must
be an instance of a business-like class, record an industry, or have an
official website. WIKIDATA_API_URL points at a mirror;
DISCOVERY_DISABLE_WIKIDATA=true turns this source off.
"""
import logging
import os
import re
from typing import Dict, List, Optional

import httpx

from src.market_scraper.market_discovery.http import request_json
from src.market_scraper.market_discovery.models import Candidate, DiscoveryQuery, ProviderResult

logger = logging.getLogger("KEEL_MARKET_DISCOVERY")
NAME = "wikidata"
API_URL = os.getenv("WIKIDATA_API_URL", "https://www.wikidata.org/w/api.php")
MAX_QUERIES = int(os.getenv("WIKIDATA_MAX_QUERIES", "3"))
PER_QUERY = 25

# ISO country -> Wikidata item, known without a request; any other country
# is looked up by its ISO code (country_item()).
COUNTRIES: Dict[str, str] = {
    "JO": "Q810", "SA": "Q851", "AE": "Q878", "KW": "Q817", "QA": "Q846", "BH": "Q398", "OM": "Q842", "EG": "Q79",
    "LB": "Q822", "SY": "Q858", "IQ": "Q796", "PS": "Q219060", "YE": "Q805", "MA": "Q1028", "DZ": "Q262", "TN": "Q948",
    "LY": "Q1016", "SD": "Q1049", "TR": "Q43", "US": "Q30", "GB": "Q145", "CA": "Q16", "FR": "Q142", "DE": "Q183",
    "IN": "Q668", "PK": "Q843", "AU": "Q408",
}
# Instance-of classes that are organisations rather than people or places.
BUSINESS_CLASSES = {
    "Q4830453",   # business
    "Q783794",    # company
    "Q6881511",   # enterprise
    "Q891723",    # public company
    "Q167037",    # corporation
    "Q507619",    # chain store
    "Q18534",     # restaurant chain (fast-food chains included)
    "Q431289",    # brand
    "Q1058914",   # software company
    "Q43229",     # organization
    "Q2085381",   # publisher
    "Q658255",    # subsidiary
    "Q1331793",   # media company
    "Q210167",    # video game developer
}
NOT_ORGANISATION = {"Q5", "Q515", "Q486972", "Q6256", "Q3624078", "Q1549591", "Q532", "Q11691"}
SOCIAL_PROPERTIES = {
    "P2003": "https://www.instagram.com/{}",
    "P2013": "https://www.facebook.com/{}",
    "P2002": "https://x.com/{}",
    "P7085": "https://www.tiktok.com/@{}",
    "P4264": "https://www.linkedin.com/company/{}",
    "P2397": "https://www.youtube.com/channel/{}",
}


def available():
    if os.getenv("DISCOVERY_DISABLE_WIKIDATA", "").lower() in ("1", "true", "yes"):
        return False, "disabled"
    return True, None


def _values(entity: dict, prop: str) -> List:
    out = []
    for claim in (entity.get("claims") or {}).get(prop) or []:
        if claim.get("rank") == "deprecated":
            continue
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(value, dict) and "id" in value:
            value = value["id"]
        elif isinstance(value, dict) and "time" in value:
            value = value["time"]
        if value is not None:
            out.append(value)
    return out


def _label(entity: dict, language: str):
    return ((entity.get("labels") or {}).get(language) or {}).get("value")


def is_organisation(entity: dict) -> bool:
    kinds = set(_values(entity, "P31"))
    if kinds & NOT_ORGANISATION:
        return False
    return bool(kinds & BUSINESS_CLASSES) or bool(_values(entity, "P452")) or bool(_values(entity, "P856"))


def parse_entities(payload: dict, query: DiscoveryQuery) -> List[Candidate]:
    out = []
    for qid, entity in ((payload or {}).get("entities") or {}).items():
        if "missing" in entity or not is_organisation(entity):
            continue
        name_en, name_ar = _label(entity, "en"), _label(entity, "ar")
        name = name_en or name_ar or _label(entity, query.language or "en")
        if not name:
            continue
        websites = [w for w in _values(entity, "P856") if isinstance(w, str)]
        social = [template.format(handle) for prop, template in SOCIAL_PROPERTIES.items()
                  for handle in _values(entity, prop)[:1] if isinstance(handle, str)]
        description = ((entity.get("descriptions") or {}).get("en") or (entity.get("descriptions") or {}).get("ar") or {}).get("value")
        inception = next((v[1:5] for v in _values(entity, "P571") if isinstance(v, str) and len(v) > 5), None)
        out.append(Candidate(
            name=name, name_ar=name_ar if name_ar != name else None, source=NAME, source_ref=qid,
            source_url=f"https://www.wikidata.org/wiki/{qid}", website=websites[0] if websites else None,
            city=query.city, country_code=query.country_code, online_only=True,
            raw={"title": name, "snippet": description, "social": social, "founded": inception},
        ))
    return out


def country_item(country_code: Optional[str]) -> Optional[str]:
    """The Wikidata item of any country, by its ISO 3166-1 code (P297)."""
    code = (country_code or "").upper()
    if code in COUNTRIES:
        return COUNTRIES[code]
    if not re.fullmatch(r"[A-Z]{2}", code):
        return None
    payload = request_json("GET", API_URL, params={
        "action": "query", "list": "search", "srsearch": f"haswbstatement:P297={code}",
        "srlimit": 1, "srnamespace": 0, "format": "json",
    }, timeout=15, cache_key_extra="wikidata-country")
    hits = (payload.get("query") or {}).get("search") or []
    return hits[0]["title"] if hits and str(hits[0].get("title", "")).startswith("Q") else None


def _search_ids(keyword: str, country_qid: str) -> List[str]:
    payload = request_json("GET", API_URL, params={
        "action": "query", "list": "search", "srsearch": f"{keyword} haswbstatement:P17={country_qid}",
        "srlimit": PER_QUERY, "srnamespace": 0, "format": "json",
    }, timeout=15, cache_key_extra="wikidata")
    return [hit["title"] for hit in ((payload.get("query") or {}).get("search") or []) if str(hit.get("title", "")).startswith("Q")]


def _entities(ids: List[str], language: str = "en") -> dict:
    languages = "|".join(dict.fromkeys(["en", "ar", language or "en"]))
    return request_json("GET", API_URL, params={
        "action": "wbgetentities", "ids": "|".join(ids[:50]), "props": "labels|descriptions|claims",
        "languages": languages, "format": "json",
    }, timeout=20, cache_key_extra="wikidata")


def _why(exc: Exception) -> str:
    """What went wrong, for the log: the HTTP status Wikimedia answered (403 usually means the User-Agent
    gives no contact - set MARKET_RESEARCH_CONTACT; 429 means too many requests), or the network error."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return f"HTTP {status}" if status else type(exc).__name__


def search(query: DiscoveryQuery) -> ProviderResult:
    ok, reason = available()
    if not ok:
        return ProviderResult(NAME, "skipped", reason=reason)
    try:
        country_qid = country_item(query.country_code)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("wikidata country lookup failed: %s", _why(exc))
        return ProviderResult(NAME, "failed", reason="unreachable", requests=1)
    if not country_qid:
        return ProviderResult(NAME, "skipped", reason="country_not_covered")
    ids, requests, failures, keywords = [], 0, 0, query.keywords[:MAX_QUERIES]
    for keyword in keywords:
        requests += 1
        try:
            ids.extend(i for i in _search_ids(keyword, country_qid) if i not in ids)
        except (httpx.HTTPError, ValueError) as exc:
            failures += 1
            logger.warning("wikidata search failed: %s", _why(exc))
    if keywords and failures == len(keywords):
        return ProviderResult(NAME, "failed", reason="unreachable", requests=requests)
    if not ids:
        return ProviderResult(NAME, "ok", [], requests=requests)
    requests += 1
    try:
        payload = _entities(ids, query.language)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("wikidata entities failed: %s", _why(exc))
        return ProviderResult(NAME, "failed", reason="unreachable", requests=requests)
    return ProviderResult(NAME, "ok", parse_entities(payload, query), requests=requests)

"""Web search (whichever provider market_scraper/web_search.py is configured
with) for
businesses with a website or social profile in the company's industry and
city - the source that finds online shops and businesses not on a map.

Listings, marketplaces, delivery apps, review sites and "top 10" articles
are not competitors themselves and are dropped; social profiles are kept
as the business they belong to."""
import logging
import os
import re
from urllib.parse import urlsplit

from src.market_scraper import web_search
from src.market_scraper.discovery import compute_website_identity_key, infer_country_code_from_domain
from src.market_scraper.market_discovery import enrich
from src.market_scraper.market_discovery.http import request_json
from src.market_scraper.market_discovery.models import Candidate, DiscoveryQuery, ProviderResult

logger = logging.getLogger("APEX_MARKET_DISCOVERY")
NAME = "web_search"
MAX_QUERIES = int(os.getenv("WEB_SEARCH_MAX_QUERIES_PER_RUN", "4"))

# Sites that list or sell for many businesses rather than being one.
NOT_A_BUSINESS = (
    "google.", "wikipedia.org", "youtube.com", "tripadvisor.", "yelp.", "foursquare.com", "zomato.com",
    "talabat.com", "careem.com", "deliveroo.", "ubereats.com", "hungerstation.com", "jahez.net", "noon.com",
    "amazon.", "ebay.", "aliexpress.", "alibaba.com", "opensooq.com", "dubizzle.", "olx.", "booking.com",
    "agoda.", "expedia.", "hotels.com", "trivago.", "airbnb.", "kayak.", "linkedin.com", "glassdoor.",
    "indeed.", "bayt.com", "yellowpages", "yell.com", "cybo.com", "wikimapia.org", "waze.com", "apple.com/maps",
    "reddit.com", "quora.com", "pinterest.", "medium.com", "blogspot.", "wordpress.com", "timeout.com",
    "lonelyplanet.", "mapquest.", "infoisinfo", "hotfrog.", "justdial.", "cylex", "zaubee", "2gis.",
    "openstreetmap.org", "bing.com", "duckduckgo.com",
)
LISTICLE = re.compile(r"\b(best|top\s*\d+|\d+\s+best|list of|near me|guide to|review of)\b|أفضل|قائمة|أشهر", re.IGNORECASE)
SOCIAL = {"instagram.com", "facebook.com", "tiktok.com", "x.com", "twitter.com"}
TITLE_SPLIT = re.compile(r"\s+[|\-–—•:]\s+")


# Internal provenance per provider (shown to customers only as "web search").
SOURCE_NAMES = {"google_cse": "google_search", "brave": "brave_search", "tavily": "tavily_search", "searxng": "searxng"}


def available():
    return (True, None) if web_search.is_configured() else (False, "not_configured")


def _cached_fetch(method, url, *, params=None, json=None, headers=None):
    # Shared 24h discovery cache; the key never includes the credential headers.
    return request_json(method, url, params=params, json_body=json, headers=headers, timeout=web_search.TIMEOUT,
                        cache_key_extra="web-search")


def _queries(query: DiscoveryQuery):
    place = query.city or ""
    out = []
    for keyword in query.keywords[:MAX_QUERIES]:
        out.append(f"{keyword} {place}".strip())
    if place and query.keywords:
        out.append(f"{query.keywords[0]} {place} site:instagram.com")
    return out[:MAX_QUERIES]


def _business_name(title: str, host: str) -> str:
    title = re.sub(r"\(@[^)]*\)", "", title or "").strip()
    title = re.sub(r"\s*[•·]\s*Instagram.*$|\s*-\s*Home\s*$|\s*\|\s*Facebook\s*$", "", title, flags=re.IGNORECASE)
    head = TITLE_SPLIT.split(title)[0].strip() if title else ""
    if 2 <= len(head) <= 80:
        return head
    return host.split(".")[0].replace("-", " ").title()


def parse(items, query: DiscoveryQuery, source: str):
    out = []
    for item in items or []:
        url = item.get("link") or item.get("url")
        title = item.get("title") or ""
        if not url:
            continue
        host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
        if not host or enrich.on_host(url, NOT_A_BUSINESS):
            continue
        if LISTICLE.search(title):
            continue
        identity = compute_website_identity_key(url)
        if host in SOCIAL and (identity is None or "/" not in identity or identity.split("/", 1)[1] in ("p", "reel", "explore", "groups", "events", "watch", "hashtag")):
            continue
        name = _business_name(title, host)
        snippet = (item.get("snippet") or item.get("content") or "")[:300]
        out.append(Candidate(
            name=name, source=source, source_ref=identity or url, source_url=url,
            website=None if host in SOCIAL else f"https://{host}",
            city=query.city, country_code=infer_country_code_from_domain(url) or None,
            categories=[], online_only=True,
            raw={"title": title[:200], "snippet": snippet, "social": host in SOCIAL},
        ))
    return out


def search(query: DiscoveryQuery) -> ProviderResult:
    ok, reason = available()
    if not ok:
        return ProviderResult(NAME, "skipped", reason=reason)
    found, calls, failures = {}, 0, 0
    for text in _queries(query):
        calls += 1
        try:
            provider, results = web_search.search(text, 15, country=query.country_code, fetch=_cached_fetch)
        except web_search.SearchFailed as exc:
            failures += 1
            logger.warning("web search failed: %s", exc)
            continue
        items = [{"url": r.url, "title": r.title, "snippet": r.snippet} for r in results]
        for candidate in parse(items, query, SOURCE_NAMES.get(provider, "web_search")):
            found.setdefault(candidate.source_ref, candidate)
    if failures and failures == calls:
        return ProviderResult(NAME, "failed", reason="unreachable", requests=calls)
    return ProviderResult(NAME, "ok", list(found.values()), requests=calls)

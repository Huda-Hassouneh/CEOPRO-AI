"""
CEOPRO AI - Industry-Agnostic Product Discovery via Google Custom Search.

The one real gap discovery.py's own docstring already names: "identifying
WHICH URLs sell a given product requires a general web-search capability
(Bing/Google Custom Search/SerpApi, etc.)". direct_search.py's SearchAction
approach only finds a seller once its domain is already known (hand-seeded
per vertical in RETAILER_DOMAINS_BY_VERTICAL, currently only electronics_
hobbyist) - it cannot, by itself, answer "who sells a coffee subscription"
or "who sells this sofa" for a tenant whose vertical nobody pre-seeded.
This module is the general answer: given any product name, a real Google
Custom Search JSON API call (same free, self-serve API social_cross_
reference.py already uses for a different purpose, same two env vars, no
new vendor decision) finds real candidate seller pages for it, regardless
of industry. Nothing here is specific to any one vertical - the query
itself comes from sector_detection.build_retail_search_query(), which is
already generic by construction.

Returns plain CandidateSource records (discovery.py's own dataclass) -
this module only ever finds URLs, exactly like direct_search.py's search
functions. It never decides collection is permitted: every candidate
still goes through discovery.py's evaluate_candidate()/register_tenant_
scoped_competitor() before anything is recorded as ALLOWED.

Setup this needs (free tier: 100 queries/day, self-serve, no lengthy app
review - identical to social_cross_reference.py's requirement, so a
tenant/operator who already set this up for social cross-referencing
needs nothing new for this):
    1. A Google Programmable Search Engine (https://programmablesearchengine.google.com/)
       configured to search the entire web - gives you a search engine ID (cx).
    2. export GOOGLE_CUSTOM_SEARCH_API_KEY=<your key>
       export GOOGLE_CUSTOM_SEARCH_CX=<your search engine id>

Never fabricates a result: a missing key/cx, an API error, or genuinely
no matches all return an empty list - the same honest-degradation
contract social_cross_reference.py and places_discovery.py already use.
"""
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional

from src.market_scraper.discovery import CandidateSource
from src.market_scraper.sector_detection import build_retail_search_query

logger = logging.getLogger("CEOPRO_AI_WEB_PRODUCT_DISCOVERY")

_CUSTOM_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"
_FETCH_TIMEOUT = 15

# Same reasoning as social_cross_reference.py: the free tier is a scarce
# 100 queries/DAY (not per-month), so default to fewer than Google's own
# 10-per-request cap rather than always maxing it out.
_MAX_RESULTS_PER_QUERY = 8


def _get(params: dict) -> Optional[dict]:
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{_CUSTOM_SEARCH_URL}?{query}", headers={"User-Agent": "CEOPRO-MarketResearchBot/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception as e:  # noqa: BLE001 - any failure here means "no data", not a crash
        logger.warning("Custom Search request failed: %s", e)
        return None


def discover_product_candidates(
    product_name: str, geo_scope: str = "",
    api_key: Optional[str] = None, cx: Optional[str] = None,
    max_results: int = _MAX_RESULTS_PER_QUERY,
) -> List[CandidateSource]:
    """
    Real Google Custom Search call for `product_name` - the query itself
    is built by sector_detection.build_retail_search_query(), which biases
    toward retail/consumer-facing results ("buy", "shop", "store", "price")
    over manufacturer/wholesale ones and optionally narrows by geo_scope.
    Nothing about this function branches on industry; it behaves the same
    way for any product name it's given.

    Returns one CandidateSource per real search result - product_name is
    the query this candidate was found for (matches direct_search.py's own
    CandidateSource shape so callers can treat both sources identically),
    url/title come straight from Google's index. Returns [] when
    GOOGLE_CUSTOM_SEARCH_API_KEY/GOOGLE_CUSTOM_SEARCH_CX aren't set, the
    call fails, or there are genuinely no results - never a guessed URL.
    """
    api_key = api_key or os.getenv("GOOGLE_CUSTOM_SEARCH_API_KEY")
    cx = cx or os.getenv("GOOGLE_CUSTOM_SEARCH_CX")
    if not api_key or not cx:
        logger.info("GOOGLE_CUSTOM_SEARCH_API_KEY/GOOGLE_CUSTOM_SEARCH_CX not set - web product discovery skipped.")
        return []

    query = build_retail_search_query(product_name, geo_scope or None)
    return _run_query(product_name, query, max_results, api_key, cx)


# Platforms a "pure social, no e-commerce site" competitor is realistically
# found on - a business that only sells through a storefront-less social
# profile. One CSE query per platform, each scoped with the site: operator
# (documented Google search syntax, not a workaround) so results are
# actual public profile/page URLs on that platform, never a guess.
_SOCIAL_DISCOVERY_SITES = ["instagram.com", "facebook.com"]


def discover_social_profile_candidates(
    product_name: str,
    api_key: Optional[str] = None, cx: Optional[str] = None,
    max_results_per_site: int = 3,
) -> List[CandidateSource]:
    """
    Finds competitors that only exist as a social profile - no e-commerce
    website at all - which discover_product_candidates() and direct_
    search.py's SearchAction approach both structurally miss (both only
    ever look for a seller's own site). One real Google Custom Search
    call per platform in _SOCIAL_DISCOVERY_SITES, `"<product_name>" site:
    <platform>` - the exact same free, self-serve API/credentials this
    module already uses, no new vendor.

    Returns real CandidateSource records pointing at the actual profile/
    post URL Google's index has - never a guessed handle. These still go
    through the same evaluate_candidate()/register_tenant_scoped_
    competitor() pipeline as any other candidate: Instagram/Facebook's
    own robots.txt disallows most paths for a generic bot (live-verified
    earlier this session - only Googlebot is allow-listed), so a
    registered social-only competitor almost always lands BLOCKED for
    direct collection of its profile page. That's correct, not a bug:
    this function's job is discovering and recording that the competitor
    exists, not deciding it's fetchable - actual data collection for a
    tracked social-only competitor already has a real, legal path
    (social_cross_reference.py's Google-index lookup, or the paid
    ScrapeCreators/Apify collectors once configured), same as it does for
    any other tracked competitor's social presence.
    """
    api_key = api_key or os.getenv("GOOGLE_CUSTOM_SEARCH_API_KEY")
    cx = cx or os.getenv("GOOGLE_CUSTOM_SEARCH_CX")
    if not api_key or not cx:
        logger.info("GOOGLE_CUSTOM_SEARCH_API_KEY/GOOGLE_CUSTOM_SEARCH_CX not set - social profile discovery skipped.")
        return []

    candidates = []
    for site in _SOCIAL_DISCOVERY_SITES:
        query = f'"{product_name}" site:{site}'
        candidates.extend(_run_query(product_name, query, max_results_per_site, api_key, cx))
    return candidates


def _run_query(
    product_name: str, query: str, max_results: int, api_key: str, cx: str,
) -> List[CandidateSource]:
    result = _get({"key": api_key, "cx": cx, "q": query, "num": min(max_results, 10)})
    if not result:
        return []
    if "error" in result:
        logger.warning("Custom Search returned an error for %r: %s", query, result["error"])
        return []

    candidates = []
    for item in (result.get("items") or []):
        link = item.get("link")
        if not link:
            continue
        candidates.append(CandidateSource(product_name, link, item.get("title") or ""))
    return candidates

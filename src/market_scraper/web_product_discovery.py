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

Two real mitigations for the 100/day free-tier cap, both real multi-
tenant scaling concerns, not hypothetical ones:

1. **Cache** (search_cache.py, Postgres-backed): pass `conn` and an
   identical query - same product name/geo scope, whether from the same
   tenant re-running discovery or a different tenant selling the same
   product - is served from cache, never re-billed against the daily
   quota. Only a genuine Google response (including a real "zero
   results" answer) is cached; a failed/errored call never is, so a
   temporary quota exhaustion doesn't get baked in as a false "no
   results" for the cache's whole TTL.
2. **SearXNG fallback** (searxng_discovery.py): when Google is
   unconfigured, fails, or errors (quota exhausted or otherwise), the
   same query is tried against a SearXNG instance next, if one is
   configured. Deliberately NOT a Bing/DuckDuckGo HTML scrape - see
   searxng_discovery.py's own docstring for why that's excluded on
   purpose, not by oversight.
3. **Quota pacer** (search_quota.py, `daily_query_limit`, default 100):
   the real primary lever for "the free tier isn't enough for a large
   catalog" - checked BEFORE every real Google call, never after, so a
   call that would exceed today's tracked count is skipped entirely
   rather than risking an accidental paid overage. Pairs with
   tenant_discovery.py's skip_already_discovered default: a daily cron
   re-running the same discovery call naturally makes incremental,
   free progress on whatever wasn't reached yesterday, no separate
   queue/resume tracking needed. SearXNG (above) stays a genuine
   resilience fallback for a real Google outage - deliberately NOT the
   primary answer to catalog volume, since a self-hosted instance
   competes for RAM on the same free-tier box this is meant to run on,
   and a public instance risks hammering someone else's free resource
   with a whole catalog's worth of queries.
"""
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional, Tuple

from src.market_scraper import search_cache, search_quota, searxng_discovery
from src.market_scraper.discovery import CandidateSource
from src.market_scraper.sector_detection import build_industry_search_query, build_retail_search_query

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


def _run_query(
    product_name: str, query: str, max_results: int, api_key: str, cx: str,
) -> Tuple[List[CandidateSource], bool]:
    """Returns (candidates, succeeded) - succeeded distinguishes a real
    Google response (even an empty one - a genuine "no results" answer)
    from a failed/errored call, so a caller can cache the former and
    fall back to SearXNG only for the latter."""
    result = _get({"key": api_key, "cx": cx, "q": query, "num": min(max_results, 10)})
    if not result:
        return [], False
    if "error" in result:
        logger.warning("Custom Search returned an error for %r: %s", query, result["error"])
        return [], False

    candidates = []
    for item in (result.get("items") or []):
        link = item.get("link")
        if not link:
            continue
        candidates.append(CandidateSource(product_name, link, item.get("title") or ""))
    return candidates, True


def _with_cache_and_fallback(
    conn, product_name: str, query: str, max_results: int,
    api_key: Optional[str], cx: Optional[str], searxng_instance_url: Optional[str],
    daily_query_limit: Optional[int],
) -> List[CandidateSource]:
    cache_key = search_cache.build_cache_key("google_cse", query)
    if conn is not None:
        cached = search_cache.get_cached(conn, cache_key)
        if cached is not None:
            return cached

    api_key = api_key or os.getenv("GOOGLE_CUSTOM_SEARCH_API_KEY")
    cx = cx or os.getenv("GOOGLE_CUSTOM_SEARCH_CX")

    # The real zero-dollar mechanism, checked BEFORE any call is made -
    # never after: once today's real Google call count hits the limit,
    # the live call is skipped entirely for the rest of today, so the
    # account never accidentally crosses into paid overage. Only
    # meaningful when conn is given (no DB, no way to track usage across
    # calls) and a limit is actually set (None = no local tracking, trust
    # Google's own account-level enforcement instead).
    quota_available = True
    if conn is not None and daily_query_limit is not None:
        quota_available = search_quota.has_budget(conn, daily_query_limit)
        if not quota_available:
            logger.info(
                "Daily Google Custom Search budget (%s) already used - skipping live call for %r, trying fallback.",
                daily_query_limit, query,
            )

    if api_key and cx and quota_available:
        if conn is not None:
            search_quota.record_query(conn)
        candidates, succeeded = _run_query(product_name, query, max_results, api_key, cx)
        if succeeded:
            if conn is not None:
                search_cache.set_cached(conn, cache_key, candidates)
            if candidates:
                return candidates
            return []  # a real, cacheable "no results" answer - no fallback needed
    elif not (api_key and cx):
        logger.info("GOOGLE_CUSTOM_SEARCH_API_KEY/GOOGLE_CUSTOM_SEARCH_CX not set - trying SearXNG fallback.")

    # Google is unconfigured, over today's budget, failed, or errored -
    # never cached, real fallback attempt.
    return searxng_discovery.discover_product_candidates(product_name, query, searxng_instance_url)


def discover_product_candidates(
    product_name: str, geo_scope: str = "",
    api_key: Optional[str] = None, cx: Optional[str] = None,
    max_results: int = _MAX_RESULTS_PER_QUERY,
    conn=None, searxng_instance_url: Optional[str] = None,
    daily_query_limit: Optional[int] = 100,
) -> List[CandidateSource]:
    """
    Real Google Custom Search call for `product_name` - the query itself
    is built by sector_detection.build_retail_search_query(), which biases
    toward retail/consumer-facing results ("buy", "shop", "store", "price")
    over manufacturer/wholesale ones and optionally narrows by geo_scope.
    Nothing about this function branches on industry; it behaves the same
    way for any product name it's given.

    Pass `conn` to enable the Postgres-backed cache and quota pacer
    (module docstring) - omit it (default) to always call live with no
    local usage tracking, same as before either existed. daily_query_limit
    (default 100, Google's real free-tier cap) is the pacer's budget -
    once today's real call count reaches it, the live call is skipped for
    the rest of today and this falls through to SearXNG instead; pass
    None to disable local tracking and trust Google's own account-level
    enforcement.

    Falls back to SearXNG (searxng_instance_url, or SEARXNG_INSTANCE_URL)
    when Google is unconfigured, over budget, fails, or errors.

    Returns one CandidateSource per real search result - product_name is
    the query this candidate was found for (matches direct_search.py's own
    CandidateSource shape so callers can treat both sources identically),
    url/title come straight from Google's (or SearXNG's) index. Returns
    [] when nothing is configured/reachable or there are genuinely no
    results - never a guessed URL.
    """
    query = build_retail_search_query(product_name, geo_scope or None)
    return _with_cache_and_fallback(
        conn, product_name, query, max_results, api_key, cx, searxng_instance_url, daily_query_limit,
    )


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
    conn=None, searxng_instance_url: Optional[str] = None,
    daily_query_limit: Optional[int] = 100,
) -> List[CandidateSource]:
    """
    Finds competitors that only exist as a social profile - no e-commerce
    website at all - which discover_product_candidates() and direct_
    search.py's SearchAction approach both structurally miss (both only
    ever look for a seller's own site). One real Google Custom Search
    call per platform in _SOCIAL_DISCOVERY_SITES, `"<product_name>" site:
    <platform>` - the exact same free, self-serve API/credentials this
    module already uses, no new vendor. Same cache/SearXNG-fallback
    behavior as discover_product_candidates() - see its docstring.

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
    candidates = []
    for site in _SOCIAL_DISCOVERY_SITES:
        query = f'"{product_name}" site:{site}'
        candidates.extend(_with_cache_and_fallback(
            conn, product_name, query, max_results_per_site, api_key, cx, searxng_instance_url, daily_query_limit,
        ))
    return candidates


def discover_industry_candidates(
    vertical: str, geo_scope: str = "",
    api_key: Optional[str] = None, cx: Optional[str] = None,
    max_results: int = _MAX_RESULTS_PER_QUERY,
    conn=None, searxng_instance_url: Optional[str] = None,
    daily_query_limit: Optional[int] = 100,
) -> List[CandidateSource]:
    """
    Domain-level discovery: "who else operates in this industry", not "who
    sells this specific product" - the real fix for a same-industry rival
    whose product mix doesn't overlap with the tenant's at all, which
    discover_product_candidates() structurally cannot find (it only ever
    searches for a seller of one named product). One real Google Custom
    Search call using build_industry_search_query() (sector_detection.py) -
    same cache/quota-pacer/SearXNG-fallback machinery as every other query
    in this module, so this doesn't add a second, ungoverned path against
    the shared 100/day free-tier budget.

    Returns CandidateSource records with product_name set to the vertical
    label used for the query (there is no specific product here) - callers
    hand these to discovery.py::register_domain_level_competitor(), not
    register_tenant_scoped_competitor() (which requires a real product_id
    to scope a mapping to).
    """
    query = build_industry_search_query(vertical, geo_scope or None)
    return _with_cache_and_fallback(
        conn, vertical, query, max_results, api_key, cx, searxng_instance_url, daily_query_limit,
    )

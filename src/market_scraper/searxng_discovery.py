"""
CEOPRO AI - SearXNG Fallback Discovery.

Real fallback for when Google Custom Search's 100/day free-tier quota is
exhausted: SearXNG (github.com/searxng/searxng) is a real, open-source,
self-hostable metasearch engine with a documented JSON API
(`{instance}/search?q=...&format=json`) - querying an instance you run
or one whose own operator has explicitly enabled API access is not a
ToS violation of anything, since SearXNG's whole design purpose is
programmatic querying.

Deliberately does NOT scrape Bing/DuckDuckGo/Google's own HTML result
pages directly, even though that was also proposed - that's a real ToS
violation of those engines (querying their sanctioned API is fine,
parsing their results page's HTML is not), the exact same distinction
social_cross_reference.py's own docstring already draws for Google
("used through Google's own official API rather than by scraping
Google's search results pages, which would itself be a ToS violation
this module deliberately avoids"). Extending that same avoidance to Bing
and DuckDuckGo is consistency, not an arbitrary new restriction.

Setup this needs: a SearXNG instance URL with its JSON API enabled -
either self-hosted (a real Docker container, free, your own
infrastructure, your own ToS) or a public instance that has opted in to
serving JSON (many public instances disable this by default specifically
to prevent the kind of automated-query load this integration would add -
check the specific instance's own usage policy before pointing real
traffic at someone else's free public instance).
    export SEARXNG_INSTANCE_URL=https://searx.example.org

Never fabricates a result: a missing instance URL, a request failure, or
genuinely no results all return [] - same honest-degradation contract as
every other discovery module in this package.
"""
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional

from src.market_scraper.discovery import CandidateSource

logger = logging.getLogger("CEOPRO_AI_SEARXNG_DISCOVERY")
_FETCH_TIMEOUT = 15


def discover_product_candidates(
    product_name: str, query: str, instance_url: Optional[str] = None, max_results: int = 8,
) -> List[CandidateSource]:
    """
    `query` is the already-built search string (same one the Google CSE
    path would have used, e.g. from sector_detection.build_retail_search_
    query()) - this function doesn't rebuild it, so both backends stay
    consistent about what they're actually searching for.
    """
    instance_url = (instance_url or os.getenv("SEARXNG_INSTANCE_URL") or "").rstrip("/")
    if not instance_url:
        logger.info("SEARXNG_INSTANCE_URL not set - SearXNG fallback skipped.")
        return []

    params = urllib.parse.urlencode({"q": query, "format": "json"})
    req = urllib.request.Request(
        f"{instance_url}/search?{params}", headers={"User-Agent": "CEOPRO-MarketResearchBot/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception as e:  # noqa: BLE001 - any failure here means "no data", not a crash
        logger.warning("SearXNG request failed: %s", e)
        return []

    candidates = []
    for item in (payload.get("results") or [])[:max_results]:
        url = item.get("url")
        if not url:
            continue
        candidates.append(CandidateSource(product_name, url, item.get("title") or ""))
    return candidates

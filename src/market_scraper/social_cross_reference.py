"""
CEOPRO AI - Social Presence Cross-Referencing via Google Custom Search.

The real, free, ToS-compliant answer to "what is this competitor doing on
social media" without touching Facebook/Instagram/TikTok directly at all:
query Google's OWN search index (built by Googlebot, which those
platforms' own robots.txt explicitly permits to crawl their public
profile/business pages - live-verified 2026-09-06: instagram.com and
facebook.com both allow-list Googlebot with only narrow disallows around
login/ajax/comment-listing paths, while a generic bot gets a blanket
Disallow) via the official Google Custom Search JSON API. This is not a
workaround or a "bypass" - it's the exact sanctioned channel those
platforms chose to permit, used through Google's own official API rather
than by scraping Google's search results pages (which would itself be a
ToS violation this module deliberately avoids).

Honest limit, stated plainly rather than oversold: this returns whatever
Google has already indexed for that profile - typically the bio/
description and, when Google has crawled and indexed it, occasional post
snippets. It is not a live feed and freshness depends entirely on
Google's own re-crawl schedule, which this module has no control over.
Treat results as "what's publicly known about them," not "what they
posted an hour ago."

Setup this needs (free tier: 100 queries/day, self-serve, no lengthy app
review):
    1. A Google Programmable Search Engine (https://programmablesearchengine.google.com/)
       configured to search the entire web - gives you a search engine ID (cx).
    2. export GOOGLE_CUSTOM_SEARCH_API_KEY=<your key>
       export GOOGLE_CUSTOM_SEARCH_CX=<your search engine id>

Never fabricates a result: a missing key/cx, an API error, or genuinely
no matches all return an empty list.
"""
import json
import logging
import os
import urllib.parse
import urllib.request
from typing import List, Optional

logger = logging.getLogger("CEOPRO_AI_SOCIAL_CROSS_REFERENCE")

_CUSTOM_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"
_FETCH_TIMEOUT = 15

# Google's own Custom Search JSON API cap: max 10 results per request.
# Kept intentionally small here (not always maxed at 10) since the free
# tier is a scarce 100 queries/DAY, not per-month like Places - every call
# this makes should be deliberate, not exploratory.
_MAX_RESULTS_PER_QUERY = 5


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


def search_social_mentions(
    query: str, api_key: Optional[str] = None, cx: Optional[str] = None,
    max_results: int = _MAX_RESULTS_PER_QUERY,
) -> List[dict]:
    """
    Real Google Custom Search call for `query` - typically a competitor
    name plus a platform hint (e.g. '"Impact Battery" instagram') or a
    direct profile URL, so the results are scoped to what Google's index
    actually has on that specific presence rather than the business in
    general.

    Returns a list of {"title", "link", "snippet"} - each one real text
    Google's own index already had, never invented. Returns [] when
    GOOGLE_CUSTOM_SEARCH_API_KEY/GOOGLE_CUSTOM_SEARCH_CX aren't set, the
    call fails, or there are genuinely no results (a real, honest outcome
    for a small/new business Google hasn't indexed much of yet - not a
    bug to route around).
    """
    api_key = api_key or os.getenv("GOOGLE_CUSTOM_SEARCH_API_KEY")
    cx = cx or os.getenv("GOOGLE_CUSTOM_SEARCH_CX")
    if not api_key or not cx:
        logger.info("GOOGLE_CUSTOM_SEARCH_API_KEY/GOOGLE_CUSTOM_SEARCH_CX not set - social cross-reference skipped.")
        return []

    result = _get({
        "key": api_key, "cx": cx, "q": query, "num": min(max_results, 10),
    })
    if not result:
        return []
    if "error" in result:
        logger.warning("Custom Search returned an error for %r: %s", query, result["error"])
        return []

    return [
        {"title": item.get("title"), "link": item.get("link"), "snippet": item.get("snippet")}
        for item in (result.get("items") or [])
    ]


def cross_reference_social_profiles(competitor_name: str, social_profiles: dict) -> dict:
    """
    Convenience wrapper for the actual use case: given a competitor name
    and the social_profiles dict direct_search.py's extract_social_profiles()
    already found (e.g. {"facebook": "https://facebook.com/...", ...}),
    runs one real, targeted Custom Search query per platform found and
    returns {"facebook": [...], "instagram": [...]}. Deliberately one query
    per known platform, not a broad exploratory search, given the 100/day
    free-tier budget.
    """
    results = {}
    for platform, url in social_profiles.items():
        query = f'"{competitor_name}" {platform}'
        results[platform] = search_social_mentions(query)
    return results

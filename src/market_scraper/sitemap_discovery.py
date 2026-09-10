"""
CEOPRO AI - Sitemap-Based Product Discovery.

Closes a real, named gap: a domain can be robots.txt-permitted and have
no schema.org SearchAction at all (live-verified this session:
seeedstudio.com, pololu.com, electromaker.io all passed the robots.txt
check but published no SearchAction, so direct_search.py correctly found
nothing there - not a bug, just the one discovery mechanism that domain
doesn't support). sitemap.xml is the other standard, machine-readable
way a site tells crawlers what its pages are - most e-commerce platforms
publish one whether or not they publish a SearchAction, so this is a
real, different discovery path, not a variant of the SearchAction one.

Same discipline as direct_search.py: every step is a real HTTP fetch,
nothing is guessed. robots.txt is checked on the domain root before
anything is fetched; if that comes back anything other than allowed,
this returns [] rather than fetching. The sitemap.xml/sitemap-index URL
itself is not separately robots-checked (the standard's whole point is
to be crawler-readable; conventionally publishers don't disallow it,
and per-page candidates found inside it still get their own real
robots.txt check downstream in discovery.py::evaluate_candidate() before
anything is ever collected from them - this module only ever finds
URLs, exactly like direct_search.py and web_product_discovery.py).

Bounded for real-world sitemap sizes (some run into hundreds of
thousands of URLs) and paced with a small per-fetch delay so a scan
doesn't look like a burst to the target site - see max_sitemaps_to_fetch/
max_urls_to_scan/fetch_delay_seconds.
"""
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from typing import List, Optional
from urllib.parse import urljoin, urlsplit

from src.market_scraper.discovery import CandidateSource, _fetch_robots_allows
from src.ai.pricing.matching import similarity

# Domains known robots.txt-allowed but with no schema.org SearchAction
# (so direct_search.py's mechanism finds nothing there) - candidates for
# THIS module's mechanism instead, but only once actually live-verified
# to publish a real, parseable sitemap with real product URLs in it.
# Starts empty on purpose, same discipline direct_search.py::
# RETAILER_DOMAINS_BY_VERTICAL used before this session's own live
# verification populated it - seeedstudio.com/pololu.com/electromaker.io
# are exactly the robots-allowed-no-SearchAction domains this session
# already found, but this sandbox's network egress can't reach them to
# confirm a sitemap actually exists there (same blocker documented
# throughout this session). scripts/live_verify_sitemap_domains.py is
# the same verify-then-wire script pattern - run it and move whichever
# domains actually pass into this dict.
SITEMAP_DOMAINS_BY_VERTICAL: dict = {}

_USER_AGENT = "CEOPRO-MarketResearchBot/1.0"
_FETCH_TIMEOUT = 15
_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_SLUG_SPLIT_RE = re.compile(r"[-_/.]+")
_ROBOTS_SITEMAP_RE = re.compile(r"^\s*Sitemap:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE)


def _fetch(url: str) -> Optional[str]:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return None


def _discover_sitemap_urls(domain: str) -> List[str]:
    """
    Real robots.txt Sitemap: directives first (the documented way a site
    tells crawlers exactly where its sitemap(s) are - a site can publish
    more than one, e.g. separate product/blog/category sitemaps).
    Falls back to the conventional /sitemap.xml path only when robots.txt
    declares none - never invents a path beyond that one well-known
    convention.
    """
    robots_text = _fetch(f"https://{domain}/robots.txt") or ""
    declared = _ROBOTS_SITEMAP_RE.findall(robots_text)
    if declared:
        return declared
    return [f"https://{domain}/sitemap.xml"]


def _slug_text(url: str) -> str:
    path = urlsplit(url).path
    last_segment = path.rstrip("/").rsplit("/", 1)[-1]
    for suffix in (".html", ".htm", ".php", ".xml"):
        if last_segment.endswith(suffix):
            last_segment = last_segment[: -len(suffix)]
            break
    return " ".join(part for part in _SLUG_SPLIT_RE.split(last_segment) if part)


def _parse_sitemap(xml_text: str, base_url: str):
    """Returns (child_sitemap_urls, page_urls) - a sitemap INDEX has only
    the former, a plain urlset only the latter. Malformed XML degrades to
    ([], []) rather than raising, consistent with every other real-fetch
    failure in this module returning an empty result, not an exception."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return [], []

    child_sitemaps, page_urls = [], []
    tag = root.tag.replace(_SITEMAP_NS, "")
    loc_tag = f"{_SITEMAP_NS}loc"
    if tag == "sitemapindex":
        for sitemap_el in root.findall(f"{_SITEMAP_NS}sitemap"):
            loc = sitemap_el.findtext(loc_tag)
            if loc:
                child_sitemaps.append(urljoin(base_url, loc.strip()))
    elif tag == "urlset":
        for url_el in root.findall(f"{_SITEMAP_NS}url"):
            loc = url_el.findtext(loc_tag)
            if loc:
                page_urls.append(urljoin(base_url, loc.strip()))
    return child_sitemaps, page_urls


def discover_products_via_sitemap(
    domain: str, product_name: str, limit: int = 5,
    max_sitemaps_to_fetch: int = 20, max_urls_to_scan: int = 5000,
    min_similarity: float = 0.35, fetch_delay_seconds: float = 0.3,
) -> List[CandidateSource]:
    """
    Real sitemap crawl for `domain`, scored against `product_name` by
    comparing it to each candidate URL's own slug text (sitemap entries
    carry no title/anchor text the way a search-results page does, so
    slug similarity is the only real signal available) - matches
    src/ai/pricing/matching.py::similarity(), the same fuzzy-match
    primitive market_source.py already uses for the analogous "does this
    real page match what we're looking for" decision, so scoring here
    isn't a new invented threshold philosophy.

    Returns [] immediately if robots.txt disallows the domain root -
    never fetches a disallowed site's sitemap. Bounded by
    max_sitemaps_to_fetch (nested sitemap indexes) and max_urls_to_scan
    (total <url> entries inspected across every sitemap fetched) so one
    call on a huge real catalog can't run unbounded; fetch_delay_seconds
    paces each real HTTP fetch.
    """
    if _fetch_robots_allows(f"https://{domain}/") is not True:
        return []

    to_fetch = list(_discover_sitemap_urls(domain))
    fetched_sitemaps = 0
    scored: List[tuple] = []
    urls_scanned = 0

    while to_fetch and fetched_sitemaps < max_sitemaps_to_fetch and urls_scanned < max_urls_to_scan:
        sitemap_url = to_fetch.pop(0)
        if fetched_sitemaps > 0:
            time.sleep(fetch_delay_seconds)
        xml_text = _fetch(sitemap_url)
        fetched_sitemaps += 1
        if not xml_text:
            continue

        child_sitemaps, page_urls = _parse_sitemap(xml_text, sitemap_url)
        to_fetch.extend(child_sitemaps)

        for page_url in page_urls:
            if urls_scanned >= max_urls_to_scan:
                break
            urls_scanned += 1
            score = similarity(_slug_text(page_url), product_name)
            if score >= min_similarity:
                scored.append((score, page_url))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [
        CandidateSource(product_name, url, _slug_text(url))
        for _, url in scored[:limit]
    ]

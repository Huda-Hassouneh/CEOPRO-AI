"""
Website enrichment: read a discovered competitor's own homepage.

For the strongest candidates that have a website, KEEL fetches the homepage
once - only where the site's robots.txt allows it, only on the public
internet, with a short timeout and a size cap - and reads what the business
publishes about itself:

- schema.org data (JSON-LD): its business type, phone, address and the
  profiles it links to (sameAs),
- the page description,
- links to its own social profiles.

The result is one more source for that competitor ("website"), so the
screen can show where each fact came from. The business type it declares
confirms (or contradicts) its industry, which feeds relevance; a site that
answers and describes the business raises confidence. Nothing is guessed:
a site that can't be read adds nothing.
"""
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from typing import List, Optional
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from src.ai.billing import credits
from src.market_scraper.market_discovery import industries
from src.market_scraper.market_discovery.http import USER_AGENT
from src.market_scraper.market_discovery.matching import Entity, domain_key
from src.market_scraper.market_discovery.models import Candidate
from src.market_scraper.network_security import UnsafeTargetError, resolve_public_addresses

logger = logging.getLogger("KEEL_MARKET_DISCOVERY")
NAME = "website"
ENRICH_MAX = int(os.getenv("DISCOVERY_ENRICH_MAX_SITES", "15"))
TIMEOUT = float(os.getenv("DISCOVERY_ENRICH_TIMEOUT_SECONDS", "8"))
MAX_BYTES = 600_000
MAX_REDIRECTS = 3
SOCIAL_HOSTS = ("instagram.com", "facebook.com", "tiktok.com", "x.com", "twitter.com", "linkedin.com", "youtube.com")
# Hosts that are platforms, not a business's own site.
NOT_OWN_SITE = SOCIAL_HOSTS + ("linktr.ee", "google.", "goo.gl", "wa.me", "bit.ly", "wixsite.com/", "business.site")


def on_host(url: str, markers) -> bool:
    """Whether a link is on one of these hosts: "g.co" matches g.co and
    x.g.co, never alfamarketeg.com; "google." any google.<tld>; a marker
    with a path ("wixsite.com/") the host and path; a word without a dot
    ("yellowpages") anywhere in the host."""
    text = (url or "").strip().lower()
    text = text.split("://", 1)[-1]
    host = text.split("/", 1)[0].split(":", 1)[0]
    for marker in markers:
        if "." not in marker and "/" not in marker:  # a brand word: "yellowpages", "careem"
            if marker in host:
                return True
            continue
        target = text if "/" in marker else host
        tail = "" if marker.endswith((".", "/")) else r"(?:[./-]|$)"
        if re.search(r"(?:^|\.)" + re.escape(marker) + tail, target):
            return True
    return False


_JSON_LD = re.compile(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)
_META = re.compile(r"<meta\s+[^>]*>", re.IGNORECASE)
_ATTR = re.compile(r"([a-zA-Z:-]+)\s*=\s*([\"'])(.*?)\2", re.DOTALL)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_HREF = re.compile(r"href\s*=\s*[\"']([^\"'#]+)[\"']", re.IGNORECASE)
_CAMEL = re.compile(r"(?<!^)(?=[A-Z])")
# schema.org types whose name doesn't match a Places type directly.
_SCHEMA_ALIASES = {
    "CafeOrCoffeeShop": ("cafe", "coffee_shop"), "FastFoodRestaurant": ("fast_food_restaurant",),
    "LodgingBusiness": ("lodging",), "GroceryStore": ("grocery_store", "supermarket"),
    "HairSalon": ("hair_salon", "beauty_salon"), "HealthAndBeautyBusiness": ("beauty_salon",),
    "MedicalClinic": ("doctor",), "AutoRepair": ("car_repair",), "ExerciseGym": ("gym",),
    "HomeAndConstructionBusiness": ("hardware_store",), "MobilePhoneStore": ("electronics_store",),
    "ComputerStore": ("electronics_store",), "BarOrPub": ("bar",), "IceCreamShop": ("ice_cream_shop",),
}


def _safe_get(client: httpx.Client, url: str, max_bytes: Optional[int] = None,
              accept: str = "text/html,application/xhtml+xml,text/plain") -> Optional[httpx.Response]:
    """GET that refuses private targets at every hop and stops at MAX_BYTES
    (or max_bytes, for a menu PDF or image). None when the redirects never end."""
    limit = max_bytes or MAX_BYTES
    for _ in range(MAX_REDIRECTS + 1):
        resolve_public_addresses(url)
        with client.stream("GET", url, headers={"User-Agent": USER_AGENT, "Accept": accept}) as response:
            if response.is_redirect and response.headers.get("location"):
                url = urljoin(url, response.headers["location"])
                continue
            body = b""
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) >= limit:
                    break
            response._content = body  # noqa: SLF001 - keep the capped body for .text
            return response
    return None


def _allowed(client: httpx.Client, homepage: str) -> bool:
    """Honours robots.txt. No robots.txt means allowed; one that can't be
    read (server error) means not allowed. Network and address errors are
    raised to the caller: an unreachable site is not a 'blocked' one."""
    response = _safe_get(client, urljoin(homepage, "/robots.txt"))
    if response is None or response.status_code >= 500:
        return False
    if response.status_code >= 400:
        return True
    parser = RobotFileParser()
    parser.parse(response.text.splitlines())
    return parser.can_fetch(USER_AGENT, homepage)


def _schema_nodes(data) -> List[dict]:
    if isinstance(data, list):
        return [n for item in data for n in _schema_nodes(item)]
    if not isinstance(data, dict):
        return []
    nodes = [data]
    for nested in data.get("@graph") or []:
        nodes.extend(_schema_nodes(nested))
    return nodes


def _types(node: dict) -> List[str]:
    value = node.get("@type") or []
    return [value] if isinstance(value, str) else [v for v in value if isinstance(v, str)]


def _text(value) -> Optional[str]:
    if isinstance(value, str):
        return unescape(value).strip() or None
    if isinstance(value, dict):
        parts = [value.get(k) for k in ("streetAddress", "addressLocality", "addressRegion", "addressCountry")]
        parts = [p if isinstance(p, str) else (p or {}).get("name") if isinstance(p, dict) else None for p in parts]
        return ", ".join(p for p in parts if p) or None
    return None


def schema_industry(schema_types: List[str]) -> Optional[str]:
    """schema.org business types -> an industry key, via the Places type table."""
    places_types = []
    for schema_type in schema_types:
        places_types.extend(_SCHEMA_ALIASES.get(schema_type, ()))
        places_types.append(_CAMEL.sub("_", schema_type).lower())
    return industries.classify_google_types(places_types)


def parse_homepage(html: str, base_url: str) -> dict:
    """What a homepage says about the business. Pure function (tested)."""
    out = {"schema_types": [], "name": None, "phone": None, "address": None, "description": None, "social": [], "title": None}
    for block in _JSON_LD.findall(html):
        try:
            data = json.loads(unescape(block.strip()))
        except ValueError:
            continue
        for node in _schema_nodes(data):
            types = _types(node)
            if not types or types == ["WebSite"] or types == ["WebPage"] or "BreadcrumbList" in types:
                continue
            out["schema_types"].extend(t for t in types if t not in out["schema_types"])
            out["name"] = out["name"] or _text(node.get("name"))
            out["phone"] = out["phone"] or _text(node.get("telephone"))
            out["address"] = out["address"] or _text(node.get("address"))
            out["description"] = out["description"] or _text(node.get("description"))
            same_as = node.get("sameAs") or []
            for link in [same_as] if isinstance(same_as, str) else same_as:
                if isinstance(link, str) and any(h in link for h in SOCIAL_HOSTS) and link not in out["social"]:
                    out["social"].append(link)
    for tag in _META.findall(html):
        attrs = {k.lower(): v for k, _q, v in _ATTR.findall(tag)}
        key = (attrs.get("name") or attrs.get("property") or "").lower()
        if key in ("description", "og:description") and not out["description"]:
            out["description"] = unescape(attrs.get("content", "")).strip() or None
        if key == "og:site_name" and not out["name"]:
            out["name"] = unescape(attrs.get("content", "")).strip() or None
    title = _TITLE.search(html)
    if title:
        out["title"] = re.sub(r"\s+", " ", unescape(title.group(1))).strip()[:200] or None
    for href in _HREF.findall(html):
        link = urljoin(base_url, href.strip())
        host = (urlsplit(link).hostname or "").lower()
        if any(host == h or host.endswith("." + h) for h in SOCIAL_HOSTS):
            path = urlsplit(link).path.strip("/")
            # A profile, not a share button or the platform's own pages.
            if path and not re.match(r"(sharer|share|intent|dialog|plugins|tr|policies|legal|privacy|help)\b", path) \
                    and link not in out["social"]:
                out["social"].append(link)
    out["social"] = out["social"][:8]
    if out["description"]:
        out["description"] = out["description"][:400]
    return out


def _own_site(entity: Entity) -> Optional[str]:
    for candidate in entity.candidates:
        site = candidate.website
        if site and not on_host(site, NOT_OWN_SITE):
            return site if "://" in site else "https://" + site
    return None


def fetch_site(url: str) -> Optional[dict]:
    """Reads one homepage, or None when it can't or mustn't be read."""
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=False) as client:
            if not _allowed(client, url):
                return {"blocked": "robots"}
            response = _safe_get(client, url)
            if response is None or response.status_code >= 400 or "html" not in response.headers.get("content-type", "html"):
                return None
            details = parse_homepage(response.text, str(response.url))
            details["final_url"] = str(response.url)
            return details
    except (httpx.HTTPError, UnsafeTargetError, UnicodeDecodeError) as exc:
        logger.info("website enrichment skipped for %s: %s", urlsplit(url).hostname, type(exc).__name__)
        return None


def enrich(ranked, fetch=fetch_site, limit: int = ENRICH_MAX) -> dict:
    """Adds a 'website' candidate to the strongest entities that have a
    site of their own. `ranked` is pipeline.rank()'s output, strongest
    first. Returns counts for the run summary."""
    targets = []
    for entity, *_rest in ranked:
        if len(targets) >= limit:
            break
        if NAME in entity.sources:
            continue
        site = _own_site(entity)
        if site:
            targets.append((entity, site))
    counts = {"checked": len(targets), "read": 0, "blocked": 0}
    if not targets:
        return counts
    with ThreadPoolExecutor(max_workers=min(6, len(targets))) as pool:
        # Each worker keeps the company's billing context (paid fetches are metered).
        pages = list(pool.map(credits.bind(lambda target: fetch(target[1])), targets))
    for (entity, site), page in zip(targets, pages):
        if not page:
            continue
        if page.get("blocked"):
            counts["blocked"] += 1
            continue
        industry_key = schema_industry(page["schema_types"]) if page["schema_types"] else None
        if not (industry_key or page["description"] or page["social"] or page["phone"]):
            continue
        counts["read"] += 1
        entity.add(Candidate(
            name=page["name"] or entity.name, source=NAME, source_ref=domain_key(site) or site,
            source_url=page.get("final_url") or site, website=site, phone=page["phone"], address=page["address"],
            categories=page["schema_types"][:6], industry_key=industry_key, online_only=entity.online_only,
            raw={"title": page["title"], "snippet": page["description"], "social": page["social"]},
        ))
    return counts

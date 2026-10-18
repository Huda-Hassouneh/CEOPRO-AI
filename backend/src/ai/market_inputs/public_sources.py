"""
KEEL - what customers see about where market data came from.

Customers buy the intelligence, not our data-acquisition setup: API
responses, screens and assistant answers name the KIND of public source
(a map listing, a web search result, the business's own website, something
the customer added) and link to the listing or page itself - never the
providers, vendors or tools we use to collect it. The exact provenance
(provider, request, timestamps) stays in the database for audit.
"""
from typing import Iterable, List, Optional

MAP_LISTING = "map_listing"
WEB_SEARCH = "web_search"
BUSINESS_WEBSITE = "business_website"
COMPANY_DATABASE = "company_database"
NEWS = "news"
ADDED_BY_YOU = "added_by_you"
DEMO = "demo"
CATEGORIES = (MAP_LISTING, WEB_SEARCH, COMPANY_DATABASE, BUSINESS_WEBSITE, NEWS, ADDED_BY_YOU, DEMO)

_CATEGORY = {
    "openstreetmap": MAP_LISTING, "overture": MAP_LISTING, "nominatim": MAP_LISTING, "photon": MAP_LISTING, "place_search": MAP_LISTING, "google_places": MAP_LISTING, "apify_google_maps": MAP_LISTING,
    "apify": MAP_LISTING, "places": MAP_LISTING, "MAP_LISTING": MAP_LISTING, "PLACES_NEARBY": MAP_LISTING,
    "google_search": WEB_SEARCH, "brave_search": WEB_SEARCH, "tavily_search": WEB_SEARCH, "searxng": WEB_SEARCH, "web_search": WEB_SEARCH, "WEB_SEARCH": WEB_SEARCH,
    "PRODUCT_SEARCH": WEB_SEARCH, "INDUSTRY_KEYWORD_SEARCH": WEB_SEARCH, "DIRECTORY": WEB_SEARCH,
    "wikidata": COMPANY_DATABASE, "gdelt": NEWS,
    "website": BUSINESS_WEBSITE, "website_intel": BUSINESS_WEBSITE, "manual": ADDED_BY_YOU, "demo": DEMO,
}
LABELS = {MAP_LISTING: "Public business listing", WEB_SEARCH: "Web search result", COMPANY_DATABASE: "Public company database",
          BUSINESS_WEBSITE: "Business website", NEWS: "News article", ADDED_BY_YOU: "Added by you", DEMO: "Demo data"}


def category(internal: Optional[str]) -> str:
    """The customer-facing kind of source for an internal provider/source key."""
    return _CATEGORY.get(internal or "", WEB_SEARCH)


def public_url(kind: str, url: Optional[str]) -> Optional[str]:
    """The link a customer may open to check a source: the public listing,
    database entry, article or web page itself. (Map listings are
    OpenStreetMap pages, whose licence asks for exactly this attribution.)"""
    return url if url and url.startswith(("https://", "http://")) else None


def merge_sources(sources: Iterable[dict]) -> List[dict]:
    """One entry per kind of source (most recent first), keeping the listing
    link: [{"source": kind, "label", "url", "last_seen_at"}]."""
    best = {}
    for s in sources or []:
        kind = category(s.get("source"))
        current = best.get(kind)
        url = public_url(kind, s.get("url"))
        if current is None or (s.get("last_seen_at") or "") > (current.get("last_seen_at") or ""):
            best[kind] = {"source": kind, "label": LABELS[kind], "url": url or (current or {}).get("url"),
                          "last_seen_at": s.get("last_seen_at")}
        elif url and not current.get("url"):
            current["url"] = url  # keep a link to check whenever one exists
    return sorted(best.values(), key=lambda s: s.get("last_seen_at") or "", reverse=True)


def provider_status(statuses: Iterable[dict]) -> List[dict]:
    """Search readiness per kind of source: ready when any provider for it is."""
    out = {}
    for p in statuses or []:
        kind = category(p.get("provider"))
        entry = out.setdefault(kind, {"provider": kind, "configured": False})  # the category, never a vendor
        entry["configured"] = entry["configured"] or bool(p.get("configured"))
    return [out[k] for k in (MAP_LISTING, COMPANY_DATABASE, WEB_SEARCH) if k in out]


_RUN_ERRORS = {"no_location", "location_not_found", "no_sources", "unreachable"}


def public_run(run: Optional[dict]) -> Optional[dict]:
    """A discovery run without provider names or raw provider errors."""
    if run is None:
        return None
    run = dict(run)
    per_kind = {}
    for provider, result in (run.get("providers") or {}).items():
        kind = category(provider)
        entry = per_kind.setdefault(kind, {"status": "skipped", "reason": None, "found": 0})
        entry["found"] += int((result or {}).get("found") or 0)
        status = (result or {}).get("status")
        if status == "ok" or (status == "failed" and entry["status"] != "ok"):
            entry["status"] = status
        elif entry["status"] == "skipped":
            entry["reason"] = (result or {}).get("reason")
    run["providers"] = per_kind
    if run.get("error") and run["error"] not in _RUN_ERRORS:
        run["error"] = "generic"
    return run

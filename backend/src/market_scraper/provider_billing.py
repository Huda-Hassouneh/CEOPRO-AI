"""
KEEL - which data provider an outgoing request goes to, and paying for it
out of the company's Data Credits (src/ai/billing/credits.py).

Every request a discovery provider, web search or collector sends goes
through metered_request(). Hosts are classified here; a host that isn't
listed is treated as a paid provider with no confirmed price, so it is
refused until an operator prices it - an unknown service is never free by
default. Public open-data services that charge nothing skip metering.
"""
import os
from typing import Callable, Dict, Optional, Tuple
from urllib.parse import urlparse

from src.ai.billing import credits

# (host, path prefix) -> (provider, operation, billable unit); the longest
# matching prefix wins.
_PAID: Dict[Tuple[str, str], Tuple[str, str, str]] = {
    ("places.googleapis.com", "/"): ("google_places", "text_search", "request"),
    ("maps.googleapis.com", "/maps/api/place/"): ("google_places", "text_search", "request"),
    ("maps.googleapis.com", "/maps/api/geocode/"): ("google_geocoding", "geocode", "request"),
    ("www.googleapis.com", "/customsearch/"): ("google_cse", "search", "request"),
    ("api.search.brave.com", "/"): ("brave_search", "search", "request"),
    ("api.tavily.com", "/"): ("tavily", "search", "request"),
    ("serpapi.com", "/"): ("serpapi", "search", "request"),
    ("api.apify.com", "/"): ("apify", "actor_run", "record"),
    # Reading a menu picture with a vision model (menu_media.py); refused until an operator sets a price.
    ("generativelanguage.googleapis.com", "/"): ("gemini_vision", "read_image", "request"),
}

# Public services with no charge (their cost_schedule rows are 0). Hosts set
# through the environment (a self-hosted SearXNG, another Nominatim) are
# added by _free_hosts().
FREE_PROVIDERS: Dict[str, str] = {
    "overpass-api.de": "openstreetmap", "overpass.private.coffee": "openstreetmap",
    "maps.mail.ru": "openstreetmap", "nominatim.openstreetmap.org": "nominatim",
    "photon.komoot.io": "photon", "www.wikidata.org": "wikidata", "query.wikidata.org": "wikidata",
    "api.gdeltproject.org": "gdelt", "overturemaps-us-west-2.s3.amazonaws.com": "overture",
    "search.openfoodfacts.org": "openfoodfacts", "prices.openfoodfacts.org": "openfoodfacts",
}
# Free by path on a shared host: the YouTube Data API is quota-limited, not billed.
_FREE_PATHS = {("www.googleapis.com", "/youtube/"): "youtube"}
_FREE_HOST_SETTINGS = {
    "SEARXNG_INSTANCE_URL": "searxng", "NOMINATIM_URL": "nominatim", "PHOTON_URL": "photon",
    "WIKIDATA_API_URL": "wikidata", "GDELT_DOC_API_URL": "gdelt", "OVERTURE_BASE_URL": "overture",
}


def _free_hosts() -> Dict[str, str]:
    hosts = dict(FREE_PROVIDERS)
    for setting, provider in _FREE_HOST_SETTINGS.items():
        host = urlparse(os.getenv(setting) or "").hostname
        if host:
            hosts[host] = provider
    return hosts


def classify(url: str) -> Optional[Tuple[str, str, str]]:
    """(provider, operation, unit) for a paid request; None for a free one."""
    parsed = urlparse(url)
    host, path = (parsed.hostname or "").lower(), parsed.path or "/"
    if host in _free_hosts() or any(host == h and path.startswith(p) for h, p in _FREE_PATHS):
        return None
    matches = [(len(p), rule) for (h, p), rule in _PAID.items() if h == host and path.startswith(p)]
    if matches:
        return max(matches)[1]
    return (f"unlisted:{host}"[:60], "request", "request")


def _apify_records(json_body) -> int:
    body = json_body if isinstance(json_body, dict) else {}
    searches = max(1, len(body.get("searchStringsArray") or []) or 1)
    places = int(body.get("maxCrawledPlacesPerSearch") or body.get("maxItems") or 50) * searches
    return max(1, places + int(body.get("maxReviews") or 0))


def metered_request(url: str, send: Callable[[], object], *, json_body=None):
    """send() performs the HTTP request and returns its parsed payload. A paid
    request is reserved from the company's Data Credits first (refused - never
    sent - when the budget, the provider's price or its controls don't allow
    it) and settled after: per request, or per record returned for providers
    that bill by record. A request that left this server and then failed is
    charged if that provider bills failed requests."""
    paid = classify(url)
    if paid is None:
        return send()
    provider, operation, unit = paid
    estimate = _apify_records(json_body) if unit == "record" else 1
    with credits.provider_call(credits.DATA, provider, operation, {unit: estimate}) as call:
        call.sent()
        payload = send()
        measured = len(payload) if unit == "record" and isinstance(payload, list) else (estimate if unit == "record" else 1)
        call.measured({unit: measured})
        return payload

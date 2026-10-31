"""
KEEL - one web-search interface for every feature that searches the web
(assistant research, competitor discovery, product/social discovery).

Why: Google's Custom Search JSON API, which these features were written
against, is closed to new customers and stops serving existing ones on
2027-01-01 (developers.google.com/custom-search/v1/overview). Callers now
ask this module for results and the provider is configuration:

    WEB_SEARCH_PROVIDERS=brave,tavily,searxng   # tried in this order

Each provider is skipped unless its credentials/URL are set, so the
default order costs nothing until an account is added:

    google_cse  GOOGLE_CUSTOM_SEARCH_API_KEY + GOOGLE_CUSTOM_SEARCH_CX (existing accounts only, until 2027-01-01)
    brave       BRAVE_SEARCH_API_KEY   ($5 monthly credit, about 1,000 searches; card on file)
    tavily      TAVILY_API_KEY         (1,000 free credits a month, no card; 1 credit per basic search)
    searxng     SEARXNG_INSTANCE_URL   (self-hosted, no key)

The first configured provider that answers wins - an empty answer is a
real answer and is returned as such; a failure moves on to the next one.
Results are plain {url, title, snippet}; which provider produced them is
returned separately for internal provenance and never shown to customers.
"""
import logging
import os
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("KEEL_WEB_SEARCH")

DEFAULT_ORDER = "google_cse,brave,tavily,searxng"
TIMEOUT = float(os.getenv("WEB_SEARCH_TIMEOUT_SECONDS", "15"))
from src.market_scraper.user_agent import USER_AGENT  # noqa: E402
from src.ai.core.env_secret import secret  # noqa: E402

GOOGLE_CSE_URL = "https://www.googleapis.com/customsearch/v1"
BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_NEWS_URL = "https://api.search.brave.com/res/v1/news/search"
TAVILY_URL = "https://api.tavily.com/search"


@dataclass(frozen=True)
class Result:
    url: str
    title: str
    snippet: str
    # When the source says it was published (news searches only); None when not stated.
    published: Optional[str] = None

    def as_dict(self) -> dict:
        return {"url": self.url, "title": self.title, "snippet": self.snippet}


class SearchFailed(Exception):
    """Every configured provider failed (or none is configured). str() stays
    "not_configured" / "unreachable" for callers that branch on it;
    `failures` says what went wrong with each provider, without secrets."""

    def __init__(self, message: str = "", failures: Optional[List[str]] = None):
        super().__init__(message)
        self.failures = failures or []


def _failure(name: str, exc: Exception) -> str:
    """One provider's failure in words safe to log and show: the HTTP status or
    the error type only - never the URL, which can carry an API key."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"{name}: HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return f"{name}: timed out"
    if isinstance(exc, httpx.HTTPError):
        return f"{name}: could not connect ({type(exc).__name__})"
    return f"{name}: unusable answer ({type(exc).__name__})"


def missing_configuration() -> str:
    """Which settings would turn web search on (names only)."""
    return ("no web search provider is configured on this server - set one of TAVILY_API_KEY, "
            "BRAVE_SEARCH_API_KEY, SEARXNG_INSTANCE_URL, or GOOGLE_CUSTOM_SEARCH_API_KEY with GOOGLE_CUSTOM_SEARCH_CX")


# fetch(method, url, *, params, json, headers) -> parsed JSON; raises on HTTP/transport errors.
Fetch = Callable[..., dict]


def _default_fetch(method: str, url: str, *, params=None, json=None, headers=None) -> dict:
    from src.market_scraper.provider_billing import metered_request

    def send():
        response = httpx.request(method, url, params=params, json=json, timeout=TIMEOUT,
                                 headers={"User-Agent": USER_AGENT, **(headers or {})})
        response.raise_for_status()
        return response.json()

    return metered_request(url, send, json_body=json)  # paid searches come out of Data Credits


def _results(items, url_key: str, snippet_key: str, limit: int) -> List[Result]:
    out = []
    for item in items or []:
        url = item.get(url_key)
        if url:
            out.append(Result(url=url, title=item.get("title") or url, snippet=item.get(snippet_key) or ""))
        if len(out) >= limit:
            break
    return out


def _google_cse(fetch: Fetch, query: str, limit: int, country: Optional[str]) -> List[Result]:
    params = {"key": os.environ["GOOGLE_CUSTOM_SEARCH_API_KEY"], "cx": os.environ["GOOGLE_CUSTOM_SEARCH_CX"],
              "q": query, "num": min(limit, 10)}
    if country:
        params["gl"] = country.lower()
    payload = fetch("GET", GOOGLE_CSE_URL, params=params)
    if "error" in payload:
        raise SearchFailed(str(payload["error"])[:200])
    return _results(payload.get("items"), "link", "snippet", limit)


def _brave(fetch: Fetch, query: str, limit: int, country: Optional[str]) -> List[Result]:
    params = {"q": query, "count": min(limit, 20)}
    if country:
        params["country"] = country.upper()
    payload = fetch("GET", BRAVE_URL, params=params,
                    headers={"Accept": "application/json", "X-Subscription-Token": secret("BRAVE_SEARCH_API_KEY")})
    return _results((payload.get("web") or {}).get("results"), "url", "description", limit)


def _tavily(fetch: Fetch, query: str, limit: int, country: Optional[str]) -> List[Result]:
    body = {"query": query, "max_results": min(limit, 20), "search_depth": "basic"}
    payload = fetch("POST", TAVILY_URL, json=body, headers={"Authorization": f"Bearer {secret('TAVILY_API_KEY')}"})
    return _results(payload.get("results"), "url", "content", limit)


def _searxng(fetch: Fetch, query: str, limit: int, country: Optional[str]) -> List[Result]:
    base = os.environ["SEARXNG_INSTANCE_URL"].rstrip("/")
    payload = fetch("GET", f"{base}/search", params={"q": query, "format": "json"})
    return _results(payload.get("results"), "url", "content", limit)


def _news_results(items, url_key: str, snippet_key: str, date_key: str, limit: int) -> List[Result]:
    out = []
    for item in items or []:
        url = item.get(url_key)
        if url:
            out.append(Result(url=url, title=item.get("title") or url, snippet=item.get(snippet_key) or "",
                              published=item.get(date_key) or None))
        if len(out) >= limit:
            break
    return out


def _brave_news(fetch: Fetch, query: str, limit: int, country: Optional[str]) -> List[Result]:
    params = {"q": query, "count": min(limit, 20), "freshness": "pm"}
    if country:
        params["country"] = country.upper()
    payload = fetch("GET", BRAVE_NEWS_URL, params=params,
                    headers={"Accept": "application/json", "X-Subscription-Token": secret("BRAVE_SEARCH_API_KEY")})
    return _news_results(payload.get("results"), "url", "description", "page_age", limit)


def _tavily_news(fetch: Fetch, query: str, limit: int, country: Optional[str]) -> List[Result]:
    body = {"query": query, "max_results": min(limit, 20), "topic": "news", "days": 90}
    payload = fetch("POST", TAVILY_URL, json=body, headers={"Authorization": f"Bearer {secret('TAVILY_API_KEY')}"})
    return _news_results(payload.get("results"), "url", "content", "published_date", limit)


def _searxng_news(fetch: Fetch, query: str, limit: int, country: Optional[str]) -> List[Result]:
    base = os.environ["SEARXNG_INSTANCE_URL"].rstrip("/")
    payload = fetch("GET", f"{base}/search", params={"q": query, "format": "json", "categories": "news"})
    return _news_results(payload.get("results"), "url", "content", "publishedDate", limit)


# Only providers with a news mode; a Google CSE key has none and is skipped for news.
NEWS_PROVIDERS: Dict[str, Callable] = {"brave": _brave_news, "tavily": _tavily_news, "searxng": _searxng_news}


@dataclass(frozen=True)
class ImageResult:
    """One picture an image search found: the picture's address, the page it sits on (when stated) and the
    words the provider gives with it (title / description), which is how a caller checks whose picture it is."""
    image_url: str
    page_url: Optional[str]
    title: str


BRAVE_IMAGES_URL = "https://api.search.brave.com/res/v1/images/search"


def _tavily_images(fetch: Fetch, query: str, limit: int, country: Optional[str]) -> List[ImageResult]:
    body = {"query": query, "max_results": min(limit, 20), "search_depth": "basic", "include_images": True,
            "include_image_descriptions": True}
    payload = fetch("POST", TAVILY_URL, json=body, headers={"Authorization": f"Bearer {secret('TAVILY_API_KEY')}"})
    out = []
    for image in payload.get("images") or []:
        url, description = (image, "") if isinstance(image, str) else (image.get("url"), image.get("description") or "")
        if url:
            out.append(ImageResult(image_url=url, page_url=None, title=description[:300]))
    return out[:limit]


def _brave_images(fetch: Fetch, query: str, limit: int, country: Optional[str]) -> List[ImageResult]:
    params = {"q": query, "count": min(limit, 50)}
    if country:
        params["country"] = country.upper()
    payload = fetch("GET", BRAVE_IMAGES_URL, params=params,
                    headers={"Accept": "application/json", "X-Subscription-Token": secret("BRAVE_SEARCH_API_KEY")})
    out = []
    for item in payload.get("results") or []:
        url = (item.get("properties") or {}).get("url") or (item.get("thumbnail") or {}).get("src")
        if url:
            out.append(ImageResult(image_url=url, page_url=item.get("url"), title=item.get("title") or ""))
    return out[:limit]


def _searxng_images(fetch: Fetch, query: str, limit: int, country: Optional[str]) -> List[ImageResult]:
    base = os.environ["SEARXNG_INSTANCE_URL"].rstrip("/")
    payload = fetch("GET", f"{base}/search", params={"q": query, "format": "json", "categories": "images"})
    out = []
    for item in payload.get("results") or []:
        url = item.get("img_src")
        if url:
            out.append(ImageResult(image_url=url, page_url=item.get("url"), title=item.get("title") or item.get("content") or ""))
    return out[:limit]


# Only providers with an image mode; a Google CSE key is skipped for images.
IMAGE_PROVIDERS: Dict[str, Callable] = {"brave": _brave_images, "tavily": _tavily_images, "searxng": _searxng_images}


def image_search(query: str, max_results: int = 10, country: Optional[str] = None,
                 fetch: Optional[Fetch] = None) -> Tuple[str, List[ImageResult]]:
    """(provider, pictures) from the first configured provider that has an image mode and answers - used to find
    menu and price-list photos published anywhere on the web. Raises SearchFailed ("not_configured" /
    "unreachable") like search()."""
    fetch = fetch or _default_fetch
    providers = [p for p in configured_providers() if p in IMAGE_PROVIDERS]
    if not providers:
        raise SearchFailed("not_configured")
    failures = []
    for name in providers:
        try:
            return name, IMAGE_PROVIDERS[name](fetch, query, max_results, country)
        except (httpx.HTTPError, ValueError, KeyError, SearchFailed) as exc:
            failures.append(_failure(name, exc))
            logger.warning("image search failed - %s", failures[-1])
    raise SearchFailed("unreachable", failures)


PROVIDERS: Dict[str, Tuple[Tuple[str, ...], Callable]] = {
    "google_cse": (("GOOGLE_CUSTOM_SEARCH_API_KEY", "GOOGLE_CUSTOM_SEARCH_CX"), _google_cse),
    "brave": (("BRAVE_SEARCH_API_KEY",), _brave),
    "tavily": (("TAVILY_API_KEY",), _tavily),
    "searxng": (("SEARXNG_INSTANCE_URL",), _searxng),
}


def configured_providers(exclude: Tuple[str, ...] = ()) -> List[str]:
    """Configured providers in WEB_SEARCH_PROVIDERS order (unknown names ignored)."""
    order = [p.strip() for p in os.getenv("WEB_SEARCH_PROVIDERS", DEFAULT_ORDER).split(",") if p.strip()]
    return [p for p in order if p in PROVIDERS and p not in exclude and all(secret(v) for v in PROVIDERS[p][0])]


def is_configured(exclude: Tuple[str, ...] = ()) -> bool:
    return bool(configured_providers(exclude))


def search(query: str, max_results: int = 10, country: Optional[str] = None,
           fetch: Optional[Fetch] = None, exclude: Tuple[str, ...] = ()) -> Tuple[str, List[Result]]:
    """(provider, results) from the first configured provider that answers.
    Raises SearchFailed when none is configured or every one failed."""
    fetch = fetch or _default_fetch
    providers = configured_providers(exclude)
    if not providers:
        raise SearchFailed("not_configured")
    failures = []
    for name in providers:
        try:
            return name, PROVIDERS[name][1](fetch, query, max_results, country)
        except (httpx.HTTPError, ValueError, KeyError, SearchFailed) as exc:
            failures.append(_failure(name, exc))
            logger.warning("web search failed - %s", failures[-1])
    raise SearchFailed("unreachable", failures)


def search_news(query: str, max_results: int = 10, country: Optional[str] = None,
                fetch: Optional[Fetch] = None) -> Tuple[str, List[Result]]:
    """(provider, news results with their publication date when stated) from the first
    configured provider that has a news mode and answers. Raises SearchFailed when none
    is set up for news ("not_configured") or every one failed ("unreachable")."""
    fetch = fetch or _default_fetch
    providers = [p for p in configured_providers() if p in NEWS_PROVIDERS]
    if not providers:
        raise SearchFailed("not_configured")
    for name in providers:
        try:
            return name, NEWS_PROVIDERS[name](fetch, query, max_results, country)
        except (httpx.HTTPError, ValueError, KeyError, SearchFailed) as exc:
            logger.warning("news search via %s failed: %s", name, exc)
    raise SearchFailed("unreachable")

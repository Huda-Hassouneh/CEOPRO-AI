"""
Where else a competitor shows up, collected from sources that allow it:
  own website feed   what the competitor itself publishes (its RSS/Atom feed,
                     found from its homepage). First-party and public.
  news search        headlines that name the competitor, from the configured
                     web-search providers that have a news mode (Brave, Tavily,
                     SearXNG - market_scraper/web_search.py). Title, link, date and
                     the snippet the provider returned; nothing generated.
  YouTube comments   public comments, with their like counts, on videos whose title
                     or channel names the competitor (YouTube Data API, needs
                     YOUTUBE_API_KEY). A like is a person who agrees.
  Google reviews     deeper than the Places API's five, with likes and the owner's
  with likes         replies, through the Apify Maps actor (needs APIFY_API_TOKEN; the older APIFY_TOKEN still works).

Google News' own RSS is deliberately not used (its terms allow personal,
non-commercial use only - see market_discovery/news.py).

Nothing here writes to the database; competitor_enrichment.py stores what these
return. Failures are raised as SourceError with a reason code, never swallowed.

FLAGGED, NOT HIDDEN: the YouTube and Apify field names below follow the vendors'
public documentation and have not been run against a live key from this
environment; parsing is tolerant (a missing or renamed field yields no item, never
an invented one). Confirm with one real run.
"""
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

import httpx
from dateutil import parser as date_parser

from src.market_scraper import web_search
from src.market_scraper.price_lookup.matching import tokens
from src.market_scraper.price_lookup.providers import fetch_html

logger = logging.getLogger("KEEL_COMPETITOR_MENTIONS")

# httpx logs every request URL at INFO, and the YouTube/other API keys travel in the query string.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

TIMEOUT = float(os.getenv("MENTIONS_TIMEOUT_SECONDS", "20"))
NEWS_MAX_AGE_DAYS = int(os.getenv("NEWS_MAX_AGE_DAYS", "180"))
MAX_ITEMS = 10
from src.market_scraper.user_agent import USER_AGENT  # noqa: E402

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_COMMENTS_URL = "https://www.googleapis.com/youtube/v3/commentThreads"
APIFY_RUN_URL = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
APIFY_MAPS_ACTOR = os.getenv("APIFY_MAPS_ACTOR", "compass~crawler-google-places")

CREDENTIALS_REJECTED = "CREDENTIALS_REJECTED"
QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
PROVIDER_ERROR = "PROVIDER_ERROR"


class SourceError(Exception):
    """A source failed; `code` is one of the reason codes competitor_enrichment stores."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")


def clean_text(value: Optional[str], limit: int = 500) -> str:
    """Plain text from a feed field: tags and entities' markup removed, whitespace collapsed, shortened."""
    import html
    text = html.unescape(_TAGS.sub(" ", value or ""))
    return _SPACES.sub(" ", text).strip()[:limit]


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for parser in (parsedate_to_datetime, date_parser.parse):
        try:
            parsed = parser(value)
        except (TypeError, ValueError, OverflowError):
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _recent(published: Optional[datetime], max_age_days: int = NEWS_MAX_AGE_DAYS) -> bool:
    """An undated item is kept (the source did not say); a dated one must be recent."""
    return published is None or published >= datetime.now(timezone.utc) - timedelta(days=max_age_days)


# ------------------------------------------------------------------ own website feed

_FEED_LINK = re.compile(r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]*>', re.I)
_HREF = re.compile(r'href=["\']([^"\']+)["\']', re.I)
_COMMON_FEEDS = ("/feed", "/rss", "/feed.xml", "/rss.xml", "/blog/feed", "/news/feed")


def discover_feed_urls(homepage_html: str, homepage_url: str) -> List[str]:
    """Feed addresses the homepage declares, then the common conventional paths."""
    found = []
    for tag in _FEED_LINK.findall(homepage_html or ""):
        href = _HREF.search(tag)
        if href:
            found.append(urljoin(homepage_url, href.group(1)))
    parts = urlsplit(homepage_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    found.extend(origin + path for path in _COMMON_FEEDS)
    seen, ordered = set(), []
    for url in found:
        if url not in seen and urlsplit(url).scheme in ("http", "https"):
            seen.add(url)
            ordered.append(url)
    return ordered


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _first(fields: dict, *names: str):
    """The first of these child elements that exists. (Not `a or b`: an XML element with no children is
    falsy, which would silently skip every plain <pubDate>.)"""
    for name in names:
        if fields.get(name) is not None:
            return fields[name]
    return None


def _node_text(node) -> Optional[str]:
    """All the text inside an element, including text nested in unescaped markup."""
    return "".join(node.itertext()) if node is not None else None


def parse_feed(xml_text: str, base_url: str) -> List[dict]:
    """RSS 2.0 / Atom entries as {url, title, summary, published_at}. A document that declares
    a DOCTYPE or entities is refused (entity-expansion attacks); malformed XML yields nothing."""
    head = (xml_text or "")[:4096].lower()
    if "<!doctype" in head or "<!entity" in head or not xml_text:
        return []
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []
    items = []
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        fields = {_local(child.tag): child for child in node}
        title = clean_text(_node_text(fields.get("title")), 300)
        link = None
        if "link" in fields:
            link = fields["link"].get("href") or (fields["link"].text or "").strip()
            for child in node:  # Atom may carry several links; prefer rel=alternate
                if _local(child.tag) == "link" and child.get("rel", "alternate") == "alternate" and child.get("href"):
                    link = child.get("href")
                    break
        if not title or not link:
            continue
        link = urljoin(base_url, link.strip())
        if urlsplit(link).scheme not in ("http", "https"):
            continue
        summary_node = _first(fields, "description", "summary", "encoded", "content")
        published = _parse_date(_node_text(_first(fields, "pubDate", "published", "updated", "date")))
        items.append({
            "url": link, "title": title, "summary": clean_text(_node_text(summary_node)) or None,
            "published_at": published.isoformat() if published else None, "_published": published,
        })
    return items


def read_own_site_news(website_url: str, fetch_document: Callable = fetch_html) -> Tuple[List[dict], Optional[str]]:
    """(items, reason): recent entries from the competitor's own feed, or why none ("NO_FEED" when
    the site publishes none, "SITE_UNREACHABLE" when its homepage could not be read)."""
    homepage = fetch_document(website_url)
    if homepage is None:
        return [], "SITE_UNREACHABLE"
    host = (urlsplit(website_url).hostname or "").removeprefix("www.")
    for feed_url in discover_feed_urls(homepage, website_url)[:5]:
        document = fetch_document(feed_url, kinds=("xml", "rss", "atom"))
        if not document:
            continue
        items = [i for i in parse_feed(document, feed_url) if _recent(i["_published"])]
        # Its own feed should link to its own pages; links elsewhere are not "published by the competitor".
        items = [i for i in items if (urlsplit(i["url"]).hostname or "").removeprefix("www.").endswith(host)]
        if items:
            items.sort(key=lambda i: i["_published"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
            for item in items:
                item.pop("_published", None)
                item["source_domain"] = host
            return items[:MAX_ITEMS], None
    return [], "NO_FEED"


# ------------------------------------------------------------------------- news search

# Words that say what kind of business it is, not which one: "Starbucks Coffee Company" is named by "Starbucks".
_GENERIC_NAME_WORDS = frozenset({
    "coffee", "company", "co", "corp", "corporation", "inc", "llc", "ltd", "limited", "group", "restaurant",
    "restaurants", "cafe", "cafes", "shop", "store", "stores", "the", "and", "&",
    "مطعم", "مقهى", "كافيه", "شركة", "مجموعة",
})


def _singular(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


# What the business sells: people write "Domino's" for "Domino's Pizza", so in a comment the kind of food is optional.
_CATEGORY_NAME_WORDS = frozenset({"pizza", "burger", "burgers", "chicken", "grill", "kitchen", "house", "bakery", "sweets", "shawarma"})


def _names_match(name: str, *texts: str, in_comment: bool = False) -> bool:
    """Does any of the texts actually name the competitor? Every distinctive word of its name must appear
    (generic words such as "coffee" or "company" are not required, unless they are all the name has)."""
    wanted = tokens(name)
    wanted = (wanted - _GENERIC_NAME_WORDS) or wanted
    if in_comment:
        wanted = (wanted - _CATEGORY_NAME_WORDS) or wanted
    if not wanted:
        return False
    haystack = tokens(" ".join(t or "" for t in texts))
    haystack = haystack | {_singular(w) for w in haystack}  # "mcdonalds" names McDonald's
    return {_singular(w) for w in wanted} <= haystack


def web_news(name: str, country_code: Optional[str], search_news: Callable = web_search.search_news) -> List[dict]:
    """News results that really mention the competitor. Raises web_search.SearchFailed
    ("not_configured" / "unreachable"); an empty list is a real answer."""
    _provider, results = search_news(f'"{name}"', max_results=15, country=country_code)
    items = []
    for result in results:
        if not result.url.startswith(("https://", "http://")) or not _names_match(name, result.title, result.snippet):
            continue
        published = _parse_date(result.published)
        if not _recent(published):
            continue
        items.append({
            "url": result.url, "title": clean_text(result.title, 300), "summary": clean_text(result.snippet) or None,
            "published_at": published.isoformat() if published else None,
            "source_domain": (urlsplit(result.url).hostname or "").removeprefix("www.") or None,
        })
        if len(items) >= MAX_ITEMS:
            break
    return items


# --------------------------------------------------------------------------- HTTP helper

def _get(url: str, params: dict, secret: Optional[str] = None, attempts: int = 2) -> Tuple[int, dict]:
    """(status, json) with one retry for a transient failure. Never returns the secret in an error."""
    last = None
    for attempt in range(attempts):
        try:
            response = httpx.get(url, params=params, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last = exc
        except httpx.HTTPError as exc:
            raise SourceError(PROVIDER_ERROR, type(exc).__name__)
        else:
            if response.status_code >= 500 and attempt + 1 < attempts:
                time.sleep(1.5)
                continue
            try:
                return response.status_code, response.json()
            except ValueError:
                return response.status_code, {}
        if attempt + 1 < attempts:
            time.sleep(1.5)
    raise SourceError(PROVIDER_ERROR, type(last).__name__ if last else "unreachable")


# ----------------------------------------------------------------------------- YouTube

def _youtube_error(status: int, payload: dict, key: str) -> Optional[SourceError]:
    if status < 400:
        return None
    error = (payload or {}).get("error") or {}
    reasons = {(e or {}).get("reason") for e in error.get("errors") or []}
    message = str(error.get("message") or "")[:200].replace(key, "***")
    if reasons & {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"}:
        return SourceError(QUOTA_EXHAUSTED, f"YouTube quota exceeded. {message}".strip())
    if reasons & {"keyInvalid", "forbidden", "accessNotConfigured", "ipRefererBlocked"} or status in (401, 403) \
            or (status == 400 and not reasons):
        return SourceError(CREDENTIALS_REJECTED, f"YouTube rejected the key ({status}). {message}".strip())
    return SourceError(PROVIDER_ERROR, f"YouTube returned {status}. {message}".strip())


# What counts as a comment worth keeping (tunable; see COMPETITOR_COMMENTS_AND_RETRY_PLAN.md P2).
MIN_COMMENT_LETTERS = int(os.getenv("COMMENT_MIN_LETTERS", "12"))
MIN_COMMENT_WORDS = int(os.getenv("COMMENT_MIN_WORDS", "3"))
# On a video whose channel does not name the competitor, an unnamed comment is kept only if it is a real opinion this long.
OFF_CHANNEL_MIN_CHARS = int(os.getenv("COMMENT_OFF_CHANNEL_MIN_CHARS", "30"))
_WORDS = re.compile(r"\w+", re.UNICODE)


def is_substantive(text: str) -> bool:
    """Enough letters (any script) and words to be an opinion: drops "first!", emoji, "nice", "+1"."""
    letters = sum(1 for ch in text or "" if ch.isalpha())
    return letters >= MIN_COMMENT_LETTERS and len(_WORDS.findall(text)) >= MIN_COMMENT_WORDS


def _normalised(text: str) -> str:
    return " ".join(_WORDS.findall((text or "").lower()))


# Words of a customer describing an experience of a business. Without the competitor's name, a comment on someone
# else's video is kept only if it reads like that (live sample, 502 comments: 80% of unnamed ones were chatter
# about the video, the presenter or other things, e.g. "why is he breathing in my ears").
_EXPERIENCE_CUES = frozenset({
    "service", "staff", "waiter", "waitress", "price", "prices", "expensive", "cheap", "overpriced", "delivery",
    "ordered", "menu", "branch", "portion", "portions", "waited", "clean", "dirty", "rude", "slow", "cold", "stale",
    "fresh", "overcharged", "refund", "reservation",
    "الخدمة", "خدمة", "الاسعار", "الأسعار", "غالي", "رخيص", "طلبت", "توصيل", "الموظفين", "موظف", "نظيف", "بارد", "بطيء",
})


def keep_comment(text: str, competitor: str, channel_names_it: bool) -> bool:
    """A comment about the business, not just the video: substantive, and either on the competitor's own
    channel, naming the competitor, or - on someone else's video - a long, considered account of an experience."""
    if not is_substantive(text):
        return False
    if channel_names_it or _names_match(competitor, text, in_comment=True):
        return True
    return len(text) >= OFF_CHANNEL_MIN_CHARS and bool(_WORDS_LOWER(text) & _EXPERIENCE_CUES)


def _WORDS_LOWER(text: str) -> set:
    return set(_WORDS.findall((text or "").lower()))


def youtube_comments(name: str, place_hint: Optional[str], api_key: str, get: Callable = _get,
                     max_videos: int = 3, per_video: int = 50, country_code: Optional[str] = None) -> List[dict]:
    """Comments (top-level first, replies after) on videos whose title or channel names the competitor.
    Videos that also name the place come first, so a chain's local branch beats a same-name video elsewhere.
    An empty list means no matching video or none with comments - a real answer."""
    params = {
        "part": "snippet", "q": " ".join(p for p in (name, place_hint) if p), "type": "video",
        "maxResults": 8, "order": "relevance", "key": api_key,
    }
    if country_code and len(country_code.strip()) == 2 and country_code.strip().isalpha():
        params["regionCode"] = country_code.strip().upper()
    status, payload = get(YOUTUBE_SEARCH_URL, params, api_key)
    error = _youtube_error(status, payload, api_key)
    if error:
        raise error
    videos = []
    for item in payload.get("items") or []:
        snippet = item.get("snippet") or {}
        video_id = (item.get("id") or {}).get("videoId")
        if video_id and _names_match(name, snippet.get("title"), snippet.get("channelTitle")):
            local = bool(place_hint) and _names_match(place_hint, snippet.get("title"), snippet.get("channelTitle"))
            videos.append((video_id, snippet.get("title") or "", _names_match(name, snippet.get("channelTitle")), local))
    videos.sort(key=lambda v: not v[3])  # stable: place-naming videos first, search order otherwise
    videos = [v[:3] for v in videos]
    comments: List[dict] = []
    seen_text = set()
    productive = 0
    for video_id, title, own_channel in videos:
        if productive >= max_videos:
            break  # a video with no comments costs 1 quota unit and does not count
        before = len(comments)
        status, payload = get(YOUTUBE_COMMENTS_URL, {
            "part": "snippet,replies", "videoId": video_id, "maxResults": per_video, "order": "relevance",
            "textFormat": "plainText", "key": api_key,
        }, api_key)
        reasons = {(e or {}).get("reason") for e in ((payload or {}).get("error") or {}).get("errors") or []}
        if status == 403 and reasons & {"commentsDisabled"}:
            continue  # this video has comments turned off; others may not
        if status == 404:
            continue
        error = _youtube_error(status, payload, api_key)
        if error:
            if error.code == QUOTA_EXHAUSTED and comments:
                break  # keep what earlier videos already gave
            raise error
        for thread in payload.get("items") or []:
            top = (thread.get("snippet") or {}).get("topLevelComment") or {}
            snippet = top.get("snippet") or {}
            text = clean_text(snippet.get("textOriginal") or snippet.get("textDisplay"), 2000)
            if not top.get("id") or not text or not keep_comment(text, name, own_channel) or _normalised(text) in seen_text:
                continue
            seen_text.add(_normalised(text))
            comments.append({
                "external_id": top["id"], "parent_external_id": None, "author": snippet.get("authorDisplayName"),
                "text": text, "likes": snippet.get("likeCount"), "published_at": snippet.get("publishedAt"),
                "reply_count": (thread.get("snippet") or {}).get("totalReplyCount"), "context": title,
                "url": f"https://www.youtube.com/watch?v={video_id}&lc={top['id']}",
            })
            for reply in ((thread.get("replies") or {}).get("comments") or []):
                rs = reply.get("snippet") or {}
                rtext = clean_text(rs.get("textOriginal") or rs.get("textDisplay"), 2000)
                if reply.get("id") and rtext and is_substantive(rtext) and _normalised(rtext) not in seen_text:
                    seen_text.add(_normalised(rtext))
                    comments.append({
                        "external_id": reply["id"], "parent_external_id": top["id"], "author": rs.get("authorDisplayName"),
                        "text": rtext, "likes": rs.get("likeCount"), "published_at": rs.get("publishedAt"),
                        "reply_count": None, "context": title, "url": f"https://www.youtube.com/watch?v={video_id}&lc={reply['id']}",
                    })
        if len(comments) > before:
            productive += 1
    return comments


# ------------------------------------------------------------- Google reviews with likes

def apify_google_reviews(place_id: str, token: str, max_reviews: int = 100, post: Optional[Callable] = None) -> List[dict]:
    """Google reviews for one place, newest first, with likes and the owner's replies, via the Apify
    Maps actor. Handles both shapes the actor can return (reviews nested under the place, or one
    review per item). Raises SourceError for a rejected token / failed run."""
    def default_post(url, params, body):
        # Paid from the company's Data Credits; refused (never sent) when they don't allow it.
        from src.market_scraper.provider_billing import metered_request

        return metered_request(url, lambda: _apify_post(url, params, body), json_body=body)

    def _apify_post(url, params, body):
        try:
            response = httpx.post(url, params=params, json=body, timeout=180)
        except httpx.HTTPError as exc:
            raise SourceError(PROVIDER_ERROR, type(exc).__name__)
        if response.status_code in (401, 403):
            raise SourceError(CREDENTIALS_REJECTED, f"Apify rejected the token ({response.status_code}).")
        if response.status_code == 402:
            raise SourceError(QUOTA_EXHAUSTED, "The Apify account has no credit left.")
        if response.status_code >= 400:
            raise SourceError(PROVIDER_ERROR, f"Apify returned {response.status_code}.")
        try:
            return response.json()
        except ValueError:
            raise SourceError(PROVIDER_ERROR, "Apify returned an unreadable answer.")

    items = (post or default_post)(
        APIFY_RUN_URL.format(actor=APIFY_MAPS_ACTOR), {"token": token},
        {"placeIds": [place_id], "maxReviews": max_reviews, "reviewsSort": "newest", "maxCrawledPlacesPerSearch": 1, "scrapeReviewerName": True},
    )
    raw = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item.get("reviews"), list):
            raw.extend(item["reviews"])
        elif item.get("text") is not None or item.get("reviewId"):
            raw.append(item)
    reviews = []
    for review in raw:
        text = clean_text(review.get("text") or review.get("textTranslated"), 3000)
        external_id = review.get("reviewId") or review.get("reviewUrl")
        if not text or not external_id:
            continue
        stars = review.get("stars")
        reviews.append({
            "external_id": str(external_id), "author": review.get("name") or review.get("reviewerName"), "text": text,
            "rating": float(stars) if isinstance(stars, (int, float)) and 0 <= stars <= 5 else None,
            "likes": review.get("likesCount"), "published_at": review.get("publishedAtDate") or review.get("publishAt"),
            "owner_reply": clean_text(review.get("responseFromOwnerText"), 2000) or None,
            "owner_reply_at": review.get("responseFromOwnerDate"),
        })
    return reviews

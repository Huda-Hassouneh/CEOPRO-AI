"""
Prices, offers and menu pictures posted on a competitor's social profiles.

Instagram and Facebook allow no direct automated collection (their terms), so
this reads the posts only through the licensed provider the platform already
uses for reviews - an Apify actor, paid per record from the company's Data
Credits (provider_billing.metered_request) - and only for profile links the
competitor published itself (SOCIAL_LINKS). An operator must also record the
approval to store this content (SOCIAL_CONTENT_APPROVAL_REFERENCE); without
it nothing is requested.

For each post:
  caption   -> price lines (same parser as page text) and offers
  picture   -> when the caption points at a menu / price / offer, or has no
               text: OCR / vision (menu_media.read_media), same limits
Facts are tagged channel = "instagram" | "facebook" and keep the POST's own
address as source (a picture address on the CDN expires); they never go into
automatic price matching until the owner confirms them (offerings.py), because
a caption is weaker evidence than a price list.

Actor field names follow the actors' published conventions and are tried
loosely (several spellings per field); verify against a real run before
relying on a field (PENDING_ACTIONS: first live run).
"""
import logging
import os
import re
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

import httpx

from src.market_scraper import competitor_mentions as mentions
from src.market_scraper.content_safety import scan_external_text
from src.market_scraper.market_discovery import enrich, intel, menu_media
from src.market_scraper.network_security import UnsafeTargetError

logger = logging.getLogger("KEEL_SOCIAL_CONTENT")

ACTORS = {
    "instagram": os.getenv("APIFY_INSTAGRAM_POSTS_ACTOR", "apify~instagram-scraper"),
    "facebook": os.getenv("APIFY_FACEBOOK_POSTS_ACTOR", "apify~facebook-posts-scraper"),
}
SUPPORTED_PLATFORMS = tuple(ACTORS)
POSTS_STANDARD, POSTS_DEEP = int(os.getenv("SOCIAL_CONTENT_POSTS", "12")), int(os.getenv("SOCIAL_CONTENT_POSTS_DEEP", "40"))
IMAGES_STANDARD, IMAGES_DEEP = int(os.getenv("SOCIAL_CONTENT_IMAGES", "5")), int(os.getenv("SOCIAL_CONTENT_IMAGES_DEEP", "15"))
CONFIDENCE_CAPTION = 0.5
CONFIDENCE_PROMOTION = 0.6
_PRICE_HINT = menu_media._MENU_WORDS  # noqa: SLF001 - the same menu / price / offer vocabulary


def _first(post: dict, *keys):
    for key in keys:
        value = post.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _image_urls(post: dict) -> List[str]:
    urls = []
    for key in ("displayUrl", "imageUrl", "thumbnailUrl", "image"):
        if isinstance(post.get(key), str):
            urls.append(post[key])
    for key in ("images", "childPosts", "media", "attachments"):
        for item in post.get(key) or []:
            if isinstance(item, str):
                urls.append(item)
            elif isinstance(item, dict):
                for inner in ("displayUrl", "imageUrl", "url", "image", "thumbnail", "uri"):
                    if isinstance(item.get(inner), str):
                        urls.append(item[inner])
                        break
    return list(dict.fromkeys(u for u in urls if u.startswith("https://")))


def normalize_posts(items, platform: str) -> List[dict]:
    """Posts in one shape: id, url, caption, images, taken_at, likes."""
    posts = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        url = _first(item, "url", "postUrl", "link", "permalink")
        caption = _first(item, "caption", "text", "message", "description") or ""
        images = _image_urls(item)
        if not url or not (caption or images):
            continue
        posts.append({
            "id": str(_first(item, "id", "postId", "shortCode") or url), "url": str(url), "caption": str(caption)[:4000],
            "images": images[:4], "taken_at": _first(item, "timestamp", "time", "date", "takenAt"),
            "likes": _first(item, "likesCount", "likes", "reactionsCount"), "platform": platform,
        })
    return posts


def fetch_posts(profile_url: str, platform: str, token: str, limit: int, post: Optional[Callable] = None) -> List[dict]:
    """The profile's newest posts through the Apify actor. Raises mentions.SourceError (rejected token, no credit,
    provider failure); a paid call refused by the company's budget raises the budget error unchanged."""
    def default_post(url, params, body):
        from src.market_scraper.provider_billing import metered_request

        def send():
            try:
                response = httpx.post(url, params=params, json=body, timeout=180)
            except httpx.HTTPError as exc:
                raise mentions.SourceError(mentions.PROVIDER_ERROR, type(exc).__name__)
            if response.status_code in (401, 403):
                raise mentions.SourceError(mentions.CREDENTIALS_REJECTED, f"Apify rejected the token ({response.status_code}).")
            if response.status_code == 402:
                raise mentions.SourceError(mentions.QUOTA_EXHAUSTED, "The Apify account has no credit left.")
            if response.status_code >= 400:
                raise mentions.SourceError(mentions.PROVIDER_ERROR, f"Apify returned {response.status_code}.")
            try:
                return response.json()
            except ValueError:
                raise mentions.SourceError(mentions.PROVIDER_ERROR, "Apify returned an unreadable answer.")
        return metered_request(url, send, json_body=body)

    url = mentions.APIFY_RUN_URL.format(actor=ACTORS[platform])
    if platform == "instagram":
        body = {"directUrls": [profile_url], "resultsType": "posts", "resultsLimit": limit, "maxItems": limit}
    else:
        body = {"startUrls": [{"url": profile_url}], "resultsLimit": limit, "maxItems": limit}
    return normalize_posts((post or default_post)(url, {"token": token}, body), platform)


def fetch_image(url: str) -> Optional[tuple]:
    """(bytes, content type) of a post picture, or None. https only, public addresses only, size-capped."""
    if not url.startswith("https://"):
        return None
    try:
        with httpx.Client(timeout=enrich.TIMEOUT, follow_redirects=False) as client:
            response = enrich._safe_get(client, url, max_bytes=menu_media.MEDIA_MAX_BYTES, accept="image/*")  # noqa: SLF001
    except (httpx.HTTPError, UnsafeTargetError, OSError):
        return None
    if response is None or response.status_code >= 400 or len(response.content) >= menu_media.MEDIA_MAX_BYTES:
        return None
    return response.content, response.headers.get("content-type", "")


_SPLIT = re.compile(r"(?:,|;|،|؛|\u2022|\u00b7|\|)\s+|\s+[-\u2013\u2014]\s+(?=\S)")


_LEAD = re.compile(r"^(?:new|now|today|special|offer|only|try|جديد|الآن|اليوم|عرض)\s*[:!\-]\s*", re.IGNORECASE)


def _caption_lines(caption: str) -> List[str]:
    """Caption text as price-parser lines: one line per item when a post lists several on one line
    ("Mansaf 8.50 JD, Falafel 1.25 JD"); a comma inside a number ("1,250") is never a split."""
    lines = []
    for raw in caption.splitlines():
        for part in _SPLIT.split(raw):
            part = re.sub(r"^[#@\W_]+", "", intel.ascii_digits(part)).strip() if not re.match(r"^\d", part.strip()) else intel.ascii_digits(part).strip()
            part = _LEAD.sub("", part)
            if 1 <= len(part) <= 220:
                lines.append(part)
    return lines


def _worth_reading(post: dict) -> bool:
    """A picture is read when its caption points at a menu / price / offer or an amount, or says nothing."""
    caption = post["caption"]
    return not caption.strip() or bool(_PRICE_HINT.search(caption)) or bool(intel._PRICE.search(intel.ascii_digits(caption)))  # noqa: SLF001


def facts_from_posts(posts: List[dict], platform: str, country: Optional[str], deep: bool = False,
                     fetch_media: Callable = fetch_image, ocr: Optional[Callable] = None) -> dict:
    """{"facts", "posts", "images_read", "images_skipped", "held_back"} - product and promotion facts from the
    posts' captions and (a bounded number of) pictures."""
    retrieved = datetime.now(timezone.utc).isoformat()
    facts: List[dict] = []
    held_back = images_read = images_skipped = 0
    budget = IMAGES_DEEP if deep else IMAGES_STANDARD
    vision = menu_media.vision_engine()
    ocr_ready = ocr is not None or menu_media.ocr_available()
    for post in posts:
        caption = post["caption"]
        if caption and scan_external_text(caption):
            held_back += 1  # the safety scan holds the caption back; its picture is still read below
            caption = ""
        base = {"channel": platform, "post_taken_at": post.get("taken_at")}
        lines = _caption_lines(caption)
        for item in intel.text_prices(lines, country, False):
            facts.append({"kind": "product", "source_url": post["url"], "retrieved_at": retrieved, "confidence": CONFIDENCE_CAPTION,
                          "type": "product", "extracted_by": "caption", **base, **item})
        for text in intel.promotions(lines):
            facts.append({"kind": "promotion", "source_url": post["url"], "retrieved_at": retrieved, "confidence": CONFIDENCE_PROMOTION,
                          "text": text, "extracted_by": "caption", **base})
        if budget > 0 and post["images"] and _worth_reading(post):
            for image_url in post["images"][:1]:  # the lead picture; the rest are usually the same menu again
                if budget <= 0:
                    break
                budget -= 1
                got = fetch_media(image_url)
                if not got:
                    continue
                lines_ocr, method = menu_media.read_media(got[0], got[1], ocr=ocr, ocr_ready=ocr_ready, vision=vision)
                if method == "skipped_no_ocr":
                    images_skipped += 1
                found = menu_media.media_facts(lines_ocr, method, post["url"], retrieved, country, intel.text_prices) if lines_ocr else []
                if found:
                    images_read += 1
                for fact in found:
                    facts.append({**fact, **base})
    return {"facts": facts, "posts": len(posts), "images_read": images_read, "images_skipped": images_skipped, "held_back": held_back}

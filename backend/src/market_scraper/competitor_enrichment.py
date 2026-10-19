"""
CEOPRO AI - Competitor Enrichment (data completeness + retry).

A discovered competitor used to be a name, a website and a score; whether
its profile, social links, prices or reviews were ever collected - and if
not, WHY - was invisible. This module closes that gap for the facets that
can be filled from official/own-site sources today:

  PROFILE       Google Places Details by place id (address, phone, rating,
                website, types, coordinates). Finds the place id first when
                the competitor was discovered some other way.
  SOCIAL_LINKS  The competitor's OWN official social profile URLs, read
                from its public homepage (schema.org sameAs, then footer
                links) - never from the social platform itself.
  REVIEWS       Google's own reviews for the competitor's Places listing
                (official API, up to 5 per place), stored as business-level
                competitor reviews - no product mapping needed - and queued
                for sentiment analysis. Gated on an operator-recorded
                approval (PLACES_TERMS_APPROVAL_REFERENCE) because Google's
                terms govern storing Places content.

Every attempt is recorded in competitor_enrichment (status + a reason code
+ human-readable detail), so a blank field always has an explanation and a
retry. Retrying is additive: COALESCE writes and a merged social_profiles
dict mean a retry can only add data or raise confidence, never blank what
is already there. Prices / reviews / social content are not collected
here; data_completeness() reports their state (derived from the data and
the policy status already in the database) so the owner sees why they are
empty, and later phases attach collectors to the same ledger.

A setup problem - Places key missing, rejected, or over quota - is a
first-class outcome (BLOCKED/FAILED with NO_CREDENTIALS /
CREDENTIALS_REJECTED / QUOTA_EXHAUSTED), never silence and never a crash.
Secrets never reach reason_detail.
"""
import hashlib
import json
import logging
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlsplit

from src.ai.pricing.matching import similarity  # noqa: F401 - kept importable for callers/tests
from src.market_scraper.name_matching import name_similarity
from src.market_scraper import direct_search
from src.market_scraper import competitor_mentions as mentions
from src.market_scraper import web_search
from src.market_scraper.category_taxonomy import categorize
from src.market_scraper.content_safety import scan_external_text
from src.market_scraper.discovery import SOCIAL_PLATFORM_HOSTS
from src.market_scraper.policy import is_public_http_url
from src.ai.billing import credits

logger = logging.getLogger("CEOPRO_AI_COMPETITOR_ENRICHMENT")

FACET_PROFILE = "PROFILE"
FACET_SOCIAL_LINKS = "SOCIAL_LINKS"
FACET_PRICES = "PRICES"
FACET_REVIEWS = "REVIEWS"
FACET_SOCIAL_CONTENT = "SOCIAL_CONTENT"
FACET_NEWS = "NEWS"
FACET_COMMENTS = "COMMENTS"
ALL_FACETS = (FACET_PROFILE, FACET_SOCIAL_LINKS, FACET_REVIEWS, FACET_NEWS, FACET_COMMENTS, FACET_PRICES, FACET_SOCIAL_CONTENT)
# The facets this module can actually (re)collect today.
ENRICHABLE_FACETS = (FACET_PROFILE, FACET_SOCIAL_LINKS, FACET_REVIEWS, FACET_NEWS, FACET_COMMENTS, FACET_PRICES)
# What the routine runs (after discovery, the sweep, "retry all failed") collect. COMMENTS searches YouTube
# (100 quota units a search), so it only runs when asked for: the per-competitor Retry, or an explicit facet.
# PRICES re-reads the whole website (and its menu files), which discovery already does on its own schedule.
ROUTINE_FACETS = (FACET_PROFILE, FACET_SOCIAL_LINKS, FACET_REVIEWS, FACET_NEWS)

STATUS_SUCCEEDED = "SUCCEEDED"
STATUS_PARTIAL = "PARTIAL"
STATUS_FAILED = "FAILED"
STATUS_BLOCKED = "BLOCKED"
STATUS_PENDING = "PENDING"
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"

NO_CREDENTIALS = "NO_CREDENTIALS"
CREDENTIALS_REJECTED = "CREDENTIALS_REJECTED"
QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
PROVIDER_ERROR = "PROVIDER_ERROR"
NO_MATCH = "NO_MATCH"
INCOMPLETE_LISTING = "INCOMPLETE_LISTING"
NO_WEBSITE = "NO_WEBSITE"
ROBOTS_DISALLOWED = "ROBOTS_DISALLOWED"
SITE_UNREACHABLE = "SITE_UNREACHABLE"
SHARED_RECORD = "SHARED_RECORD"
NO_PRODUCTS_MAPPED = "NO_PRODUCTS_MAPPED"
TERMS_UNREVIEWED = "TERMS_UNREVIEWED"
NO_DATA_COLLECTED = "NO_DATA_COLLECTED"
COLLECTOR_NOT_ENABLED = "COLLECTOR_NOT_ENABLED"
NO_SOCIAL_LINKS = "NO_SOCIAL_LINKS"
NO_PLACE_ID = "NO_PLACE_ID"
PLATFORM_APPROVAL_MISSING = "PLATFORM_APPROVAL_MISSING"
SERVICE_MISCONFIGURED = "SERVICE_MISCONFIGURED"
NOT_ATTEMPTED = "NOT_ATTEMPTED"
NO_FEED = "NO_FEED"
NO_NEWS = "NO_NEWS"
NO_VIDEOS = "NO_VIDEOS"
NO_PRICES_PUBLISHED = "NO_PRICES_PUBLISHED"
JS_RENDERED = "JS_RENDERED"
OCR_NOT_AVAILABLE = "OCR_NOT_AVAILABLE"
NOT_OWN_SITE = "NOT_OWN_SITE"
ACTION_REVIEW_SOURCE = "review_source"

# Transient failures are retried automatically by a later sweep after this long.
_RETRY_AFTER = timedelta(hours=int(os.getenv("ENRICHMENT_RETRY_AFTER_HOURS", "6")))
# Minimum gap between two manual attempts at the same facet (stops a double
# click or a script from hammering a paid API).
MIN_SECONDS_BETWEEN_ATTEMPTS = int(os.getenv("ENRICHMENT_MIN_RETRY_SECONDS", "30"))

_FIND_PLACE_URL = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
_FETCH_TIMEOUT = 15
_NAME_MATCH_THRESHOLD = 0.82  # same bar spiders/google_places.py uses
_MAX_PLACE_CANDIDATES = 3
_DETAIL_FIELDS = "place_id,name,website,formatted_address,formatted_phone_number,rating,user_ratings_total,types,geometry,reviews"
# Footer "share this page" links are not the business's own profile.
_SHARE_PATH_MARKERS = ("sharer", "/share", "intent/", "dialog/", "plugins/")


class _PlacesError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _redact(text: str, secret: Optional[str]) -> str:
    return text.replace(secret, "***") if secret and text else text


def _places_get(url: str, params: dict, api_key: str) -> dict:
    """One Places call. Returns the JSON payload, or raises _PlacesError with a
    classified, secret-free cause - the part the old helpers swallowed."""
    query = urllib.parse.urlencode({**params, "key": api_key})
    request = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": "CEOPRO-MarketResearchBot/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=_FETCH_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8", errors="ignore"))
    except Exception as exc:  # noqa: BLE001 - classified below, never raised raw
        raise _PlacesError(PROVIDER_ERROR, _redact(f"{type(exc).__name__}: {exc}", api_key)[:300])
    status = payload.get("status")
    if status in ("OK", "ZERO_RESULTS"):
        return payload
    message = _redact(str(payload.get("error_message") or ""), api_key)[:300]
    if status == "REQUEST_DENIED":
        raise _PlacesError(CREDENTIALS_REJECTED, f"Google rejected the request (REQUEST_DENIED). {message}".strip())
    if status == "OVER_QUERY_LIMIT":
        raise _PlacesError(QUOTA_EXHAUSTED, f"Google quota exceeded (OVER_QUERY_LIMIT). {message}".strip())
    raise _PlacesError(PROVIDER_ERROR, f"Google returned status {status}. {message}".strip())


def _host(url: Optional[str]) -> str:
    hostname = (urlsplit(url or "").hostname or "").lower()
    return hostname[4:] if hostname.startswith("www.") else hostname


def _write_ledger(
    conn, tenant_id: str, competitor_id: str, facet: str, status: str,
    reason_code: Optional[str] = None, reason_detail: Optional[str] = None,
    provider: Optional[str] = None, items_found: int = 0, data_confidence: Optional[float] = None,
) -> None:
    transient = reason_code in (PROVIDER_ERROR, QUOTA_EXHAUSTED, SITE_UNREACHABLE)
    now = datetime.now(timezone.utc)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO competitor_enrichment
                (tenant_id, global_competitor_id, facet, status, reason_code, reason_detail, provider,
                 attempts, items_found, data_confidence, last_attempt_at, next_retry_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 1, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, global_competitor_id, facet) DO UPDATE SET
                status = EXCLUDED.status, reason_code = EXCLUDED.reason_code,
                reason_detail = EXCLUDED.reason_detail, provider = EXCLUDED.provider,
                attempts = competitor_enrichment.attempts + 1,
                items_found = EXCLUDED.items_found, data_confidence = EXCLUDED.data_confidence,
                last_attempt_at = EXCLUDED.last_attempt_at, next_retry_at = EXCLUDED.next_retry_at,
                updated_at = EXCLUDED.updated_at;
            """,
            (
                tenant_id, competitor_id, facet, status, reason_code, reason_detail, provider,
                items_found, data_confidence, now, now + _RETRY_AFTER if transient else None, now,
            ),
        )
    conn.commit()


def _load_competitor(conn, tenant_id: str, competitor_id: str) -> Optional[dict]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT gc.competitor_name, gc.website_url, gc.website_identity_key, gc.address, gc.city, gc.phone,
                   gc.rating, gc.rating_count, gc.place_types, gc.google_place_id, gc.latitude, gc.longitude,
                   gc.social_profiles, gc.visibility, gc.added_by_tenant_id
            FROM tenant_competitors tc
            JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
            WHERE tc.tenant_id = %s AND tc.global_competitor_id = %s;
            """,
            (tenant_id, competitor_id),
        )
        row = cursor.fetchone()
    if not row:
        return None
    keys = (
        "name", "website_url", "identity_key", "address", "city", "phone", "rating", "rating_count",
        "place_types", "place_id", "latitude", "longitude", "social_profiles", "visibility", "owner_tenant_id",
    )
    competitor = dict(zip(keys, row))
    competitor["owner_tenant_id"] = str(competitor["owner_tenant_id"]) if competitor["owner_tenant_id"] else None
    return competitor


def _find_place(competitor: dict, api_key: str) -> "tuple[Optional[dict], Optional[float]]":
    """Locates this competitor's place and returns (details, confidence).
    Accepts a candidate only on evidence: its website host equals ours
    (0.95) or its name is similar enough (0.8). Never takes the first hit."""
    query = " ".join(part for part in (competitor["name"], competitor["address"] or competitor["city"]) if part)
    params = {"input": query, "inputtype": "textquery", "fields": "place_id,name"}
    if competitor["latitude"] is not None and competitor["longitude"] is not None:
        params["locationbias"] = f"point:{competitor['latitude']},{competitor['longitude']}"
    found = _places_get(_FIND_PLACE_URL, params, api_key)
    our_host = _host(competitor["website_url"])
    for candidate in (found.get("candidates") or [])[:_MAX_PLACE_CANDIDATES]:
        place_id = candidate.get("place_id")
        if not place_id:
            continue
        details = (_places_get(_DETAILS_URL, {"place_id": place_id, "fields": _DETAIL_FIELDS}, api_key)).get("result") or {}
        details["place_id"] = place_id
        if our_host and _host(details.get("website")) == our_host:
            return details, 0.95
        if name_similarity(details.get("name") or candidate.get("name") or "", competitor["name"]) >= _NAME_MATCH_THRESHOLD:
            return details, 0.8
    return None, None


@credits.metered("competitor_enrichment")
def enrich_profile(
    conn, tenant_id: str, competitor_id: str, competitor: dict, api_key: Optional[str], context: Optional[dict] = None,
) -> dict:
    if competitor["visibility"] != "PRIVATE" or competitor["owner_tenant_id"] != str(tenant_id):
        outcome = (STATUS_NOT_APPLICABLE, SHARED_RECORD, "This competitor record is shared across tenants and cannot be edited.", None, 0, None)
    elif not api_key:
        outcome = (STATUS_BLOCKED, NO_CREDENTIALS, "GOOGLE_PLACES_API_KEY is not set for the service that enriches competitors.", None, 0, None)
    else:
        outcome = _profile_outcome(conn, tenant_id, competitor_id, competitor, api_key, context)
    status, reason_code, detail, provider, items, confidence = outcome
    _write_ledger(conn, tenant_id, competitor_id, FACET_PROFILE, status, reason_code, detail, provider, items, confidence)
    return {"status": status, "reason_code": reason_code, "reason_detail": detail, "items_found": items}


def _profile_outcome(conn, tenant_id, competitor_id, competitor, api_key, context=None):
    provider = "google_places"
    try:
        if competitor["place_id"]:
            details = (_places_get(_DETAILS_URL, {"place_id": competitor["place_id"], "fields": _DETAIL_FIELDS}, api_key)).get("result") or {}
            details["place_id"] = competitor["place_id"]
            confidence = 1.0
        else:
            details, confidence = _find_place(competitor, api_key)
    except _PlacesError as exc:
        return STATUS_FAILED, exc.code, exc.detail, provider, 0, None
    if not details:
        return STATUS_FAILED, NO_MATCH, "No Google Places listing matched this competitor's name or website.", provider, 0, None

    if context is not None:
        context["details"] = details  # REVIEWS reuses this same (already billed) Details call
    location = (details.get("geometry") or {}).get("location") or {}
    types = details.get("types")
    categorization = categorize(competitor["name"], tuple(types) if types else None)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE global_competitors SET
                google_place_id = COALESCE(google_place_id, %s),
                website_url = COALESCE(website_url, %s),
                address = COALESCE(address, %s),
                phone = COALESCE(phone, %s),
                rating = COALESCE(%s, rating),
                rating_count = COALESCE(%s, rating_count),
                place_types = COALESCE(place_types, %s),
                category_path = COALESCE(category_path, %s),
                latitude = COALESCE(latitude, %s),
                longitude = COALESCE(longitude, %s)
            WHERE global_competitor_id = %s AND visibility = 'PRIVATE' AND added_by_tenant_id = %s;
            """,
            (
                details.get("place_id"), details.get("website") or None,
                details.get("formatted_address"), details.get("formatted_phone_number"),
                details.get("rating"), details.get("user_ratings_total"),
                list(types) if types else None,
                list(categorization.path) if categorization else None,
                location.get("lat"), location.get("lng"),
                competitor_id, tenant_id,
            ),
        )
    conn.commit()

    refreshed = _load_competitor(conn, tenant_id, competitor_id) or competitor
    populated = sum(1 for key in ("address", "phone", "rating", "website_url", "place_types") if refreshed.get(key))
    complete = bool(refreshed.get("address")) and refreshed.get("rating") is not None
    if complete:
        return STATUS_SUCCEEDED, None, None, provider, populated, confidence
    return STATUS_PARTIAL, INCOMPLETE_LISTING, "Listing found but it has no address or rating on Google.", provider, populated, confidence


def _is_share_link(url: str) -> bool:
    lowered = url.lower()
    return any(marker in lowered for marker in _SHARE_PATH_MARKERS)


@credits.metered("competitor_enrichment")
def enrich_social_links(conn, tenant_id: str, competitor_id: str, competitor: dict) -> dict:
    status, reason_code, detail, items, confidence = _social_outcome(conn, tenant_id, competitor_id, competitor)
    _write_ledger(conn, tenant_id, competitor_id, FACET_SOCIAL_LINKS, status, reason_code, detail, "own_website", items, confidence)
    return {"status": status, "reason_code": reason_code, "reason_detail": detail, "items_found": items}


def _social_outcome(conn, tenant_id, competitor_id, competitor):
    if competitor["visibility"] != "PRIVATE" or competitor["owner_tenant_id"] != str(tenant_id):
        return STATUS_NOT_APPLICABLE, SHARED_RECORD, "This competitor record is shared across tenants and cannot be edited.", 0, None
    website = competitor["website_url"]
    if not website:
        return STATUS_NOT_APPLICABLE, NO_WEBSITE, "This competitor has no website to read social links from.", 0, None

    existing = dict(competitor["social_profiles"] or {})
    found: dict = {}
    confidence = 0.95

    identity = competitor["identity_key"] or ""
    social_host = identity.split("/")[0]
    if "/" in identity and social_host in SOCIAL_PLATFORM_HOSTS:
        # The competitor IS a social profile (found via social search).
        platform = direct_search._classify_social_url(website)
        if platform:
            found[platform] = website
        confidence = 1.0
    else:
        if not is_public_http_url(website):
            return STATUS_BLOCKED, ROBOTS_DISALLOWED, "The website is not a public http(s) address.", 0, None
        if direct_search._robots_allowed_cached(website) is False:
            return STATUS_BLOCKED, ROBOTS_DISALLOWED, "The website's robots.txt disallows automated access.", 0, None
        html = direct_search._fetch(website)
        if not html:
            return STATUS_FAILED, SITE_UNREACHABLE, "The website could not be fetched.", 0, None
        extracted = direct_search.extract_social_profiles(html)
        for platform, url in extracted["profiles"].items():
            if _is_share_link(url):
                continue
            found[platform] = url
            if extracted["sources"].get(platform) != "sameAs":
                confidence = min(confidence, 0.6)

    if not found:
        return STATUS_FAILED, NO_SOCIAL_LINKS, "No official social profile links were published on the website.", len(existing), None

    merged = {**found, **existing}  # a link already stored wins; a retry only adds
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE global_competitors SET social_profiles = %s::jsonb "
            "WHERE global_competitor_id = %s AND visibility = 'PRIVATE' AND added_by_tenant_id = %s;",
            (json.dumps(merged), competitor_id, tenant_id),
        )
    conn.commit()
    return STATUS_SUCCEEDED, None, None, len(merged), confidence


def _stable_review_id(place_id: str, review: dict) -> str:
    """Places reviews carry no id; author + timestamp identify one. Hashed so
    the id is a fixed-size, PII-free dedupe key (the author's name is stored
    separately in reviewer_name)."""
    raw = f"{place_id}|{review.get('author_name', 'anonymous')}|{review.get('time')}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _places_review_records(place_id: str, raw_reviews) -> list:
    records = []
    for review in raw_reviews or []:
        body = " ".join(str(review.get("text") or "").split())
        if not body:
            continue
        flags = scan_external_text(body)
        timestamp = review.get("time")
        records.append({
            "external_review_id": _stable_review_id(place_id, review),
            "review_text": body,
            "reviewer_name": review.get("author_name"),
            "review_rating": review.get("rating"),
            "review_date": datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat() if isinstance(timestamp, (int, float)) else None,
            "safety_status": "QUARANTINED" if flags else "SAFE",
            "safety_flags": flags,
        })
    return records


def _review_source(
    conn, tenant_id: str, actor_user_id: str, approval_reference: str, *,
    name: str, collector_key: str, retention_days: Optional[int] = None,
) -> str:
    """The tenant's one data source for `collector_key`, created on first use. It is ALLOWED on the
    strength of the OPERATOR's recorded approval (approval_reference) - these are licensed APIs, not
    sites whose terms each tenant must review - with the same audited approval fields
    chk_allowed_source_has_approval demands of every ALLOWED row. retention_days is set where the
    provider's terms require stored data to be refreshed or deleted (YouTube: 30)."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT source_id FROM data_sources WHERE tenant_id = %s AND collector_key = %s "
            "AND source_type = 'OFFICIAL_API' AND is_active = TRUE ORDER BY created_at LIMIT 1;",
            (tenant_id, collector_key),
        )
        row = cursor.fetchone()
        if row:
            return str(row[0])
        cursor.execute(
            """
            INSERT INTO data_sources
                (tenant_id, source_name, source_type, collector_key, policy_status, is_active,
                 approval_reference, approved_by, approved_at, privacy_reviewed_at, retention_days)
            VALUES (%s, %s, 'OFFICIAL_API', %s, 'ALLOWED', TRUE, %s, %s, NOW(), NOW(), COALESCE(%s, 90))
            RETURNING source_id;
            """,
            (tenant_id, name, collector_key, approval_reference, actor_user_id, retention_days),
        )
        source_id = str(cursor.fetchone()[0])
    conn.commit()
    return source_id


def _places_review_source(conn, tenant_id: str, actor_user_id: str, approval_reference: str) -> str:
    return _review_source(conn, tenant_id, actor_user_id, approval_reference,
                          name="Google Places (official API)", collector_key="google_places")


def _request_sentiment_analysis(tenant_id: str) -> None:
    """Same market.analysis.requested event persistence.py publishes after a
    scrape, so new reviews get sentiment + score refresh. Best effort: the
    reviews are already saved, a missed event is fixed by the next analysis."""
    import redis
    from src.ai.core.redis_client import get_redis_client  # honours REDIS_URL / password / TLS like every other publisher
    try:
        client = get_redis_client()
        client.xadd("market.analysis.requested", {"tenant_id": tenant_id, "job_id": "", "review_count": "0"})
    except redis.RedisError:
        logger.warning("could not request sentiment analysis for tenant %s", tenant_id)


@credits.metered("competitor_enrichment")
def enrich_reviews(
    conn, tenant_id: str, competitor_id: str, competitor: dict, api_key: Optional[str],
    context: Optional[dict] = None, actor_user_id: Optional[str] = None,
) -> dict:
    outcome = _reviews_outcome(conn, tenant_id, competitor_id, competitor, api_key, context, actor_user_id)
    status, reason_code, detail, items, confidence = outcome
    _write_ledger(conn, tenant_id, competitor_id, FACET_REVIEWS, status, reason_code, detail, "google_places", items, confidence)
    return {"status": status, "reason_code": reason_code, "reason_detail": detail, "items_found": items}


def _reviews_outcome(conn, tenant_id, competitor_id, competitor, api_key, context, actor_user_id):
    if competitor["visibility"] != "PRIVATE" or competitor["owner_tenant_id"] != str(tenant_id):
        return STATUS_NOT_APPLICABLE, SHARED_RECORD, "This competitor record is shared across tenants and cannot be edited.", 0, None
    if not api_key:
        return STATUS_BLOCKED, NO_CREDENTIALS, "GOOGLE_PLACES_API_KEY is not set for the service that enriches competitors.", 0, None
    approval = os.getenv("PLACES_TERMS_APPROVAL_REFERENCE", "").strip()
    if not approval:
        return (
            STATUS_BLOCKED, PLATFORM_APPROVAL_MISSING,
            "The operator has not recorded approval to store Google Places reviews (PLATFORM setting PLACES_TERMS_APPROVAL_REFERENCE).",
            0, None,
        )
    actor = actor_user_id or os.getenv("SCRAPER_ACTOR_USER_ID") or os.getenv("AI_SERVICE_ACTOR_USER_ID")
    if not actor:
        return STATUS_FAILED, SERVICE_MISCONFIGURED, "No acting user is configured for this service (SCRAPER_ACTOR_USER_ID).", 0, None
    place_id = competitor["place_id"] or ((context or {}).get("details") or {}).get("place_id")
    if not place_id:
        return STATUS_FAILED, NO_PLACE_ID, "No Google listing is known for this competitor yet; retry the profile first.", 0, None

    details = (context or {}).get("details")
    if not details or details.get("place_id") != place_id:
        # No fresh Details from this run's profile step (e.g. REVIEWS retried alone).
        try:
            details = (_places_get(_DETAILS_URL, {"place_id": place_id, "fields": "place_id,reviews"}, api_key)).get("result") or {}
        except _PlacesError as exc:
            return STATUS_FAILED, exc.code, exc.detail, 0, None
    records = _places_review_records(place_id, details.get("reviews"))
    # The same token as competitor discovery (apify_maps.py); APIFY_TOKEN is its older name.
    deep_token = (os.getenv("APIFY_API_TOKEN") or os.getenv("APIFY_TOKEN") or "").strip()
    if not records and not deep_token:
        return STATUS_FAILED, NO_DATA_COLLECTED, "Google returned no review text for this listing.", 0, None

    source_id = _places_review_source(conn, tenant_id, actor, approval)
    new_reviews = 0
    with conn.cursor() as cursor:
        for record in records:
            cursor.execute(
                """
                INSERT INTO reviews
                    (tenant_id, product_id, source_platform, reviewer_name, review_text, review_rating,
                     review_date, subject_type, competitor_id, source_status, collection_method,
                     source_id, external_review_id, safety_status, safety_flags)
                VALUES (%s, NULL, 'Google Places', %s, %s, %s, COALESCE(%s::timestamptz, NOW()),
                        'COMPETITOR', %s, 'ALLOWED', 'PUBLIC_API', %s, %s, %s, %s::jsonb)
                ON CONFLICT (tenant_id, source_id, external_review_id)
                    WHERE source_id IS NOT NULL AND external_review_id IS NOT NULL
                DO UPDATE SET review_text = EXCLUDED.review_text, review_rating = EXCLUDED.review_rating
                RETURNING (xmax = 0);
                """,
                (
                    tenant_id, record["reviewer_name"], record["review_text"], record["review_rating"],
                    record["review_date"], competitor_id, source_id, record["external_review_id"],
                    record["safety_status"], json.dumps(record["safety_flags"]),
                ),
            )
            new_reviews += 1 if cursor.fetchone()[0] else 0
        cursor.execute(
            "SELECT data_confidence FROM competitor_enrichment WHERE tenant_id = %s AND global_competitor_id = %s AND facet = 'PROFILE';",
            (tenant_id, competitor_id),
        )
        row = cursor.fetchone()
    conn.commit()
    confidence = row[0] if row else None

    # Places returns at most 5 reviews per listing. With an Apify token the same listing is read
    # deeper - more reviews, with likes and the owner's replies - without double-storing the 5.
    deep_total, deep_new, deep_error = 0, 0, None
    if deep_token:
        try:
            deep_new, deep_total = _store_deep_google_reviews(conn, tenant_id, competitor_id, place_id, source_id, deep_token)
        except mentions.SourceError as exc:
            conn.rollback()
            deep_error = exc
    if new_reviews or deep_new:
        _request_sentiment_analysis(tenant_id)

    total = len(records) + deep_total
    if total == 0:
        code = deep_error.code if deep_error else NO_DATA_COLLECTED
        return STATUS_FAILED, code, (deep_error.detail if deep_error else "Google returned no review text for this listing."), 0, None
    if deep_error:
        return (STATUS_PARTIAL, deep_error.code,
                f"Google's own API gave {len(records)} reviews; the deeper source failed: {deep_error.detail}", total, confidence)
    return STATUS_SUCCEEDED, None, None, total, confidence


def _store_deep_google_reviews(conn, tenant_id: str, competitor_id: str, place_id: str, source_id: str, token: str) -> "tuple[int, int]":
    """Reads the listing's reviews through the Apify actor and stores them. Returns (new, total).
    A review already stored from the Places API (same author, one text opening the other - Places and the actor can differ in how much of a long review they return) is not
    duplicated - it just gains the like count the Places API never gives. An owner's reply is
    stored under the review it answers. Likes are one more person agreeing."""
    reviews = mentions.apify_google_reviews(place_id, token, max_reviews=int(os.getenv("APIFY_REVIEWS_MAX", "100")))
    new = 0
    with conn.cursor() as cursor:
        for review in reviews:
            flags = scan_external_text(review["text"])
            cursor.execute(
                """
                SELECT review_id FROM reviews
                WHERE tenant_id = %s AND competitor_id = %s AND subject_type = 'COMPETITOR' AND parent_review_id IS NULL
                  AND LOWER(COALESCE(reviewer_name, '')) = LOWER(COALESCE(%s, ''))
                  AND LEFT(review_text, LEAST(60, LENGTH(review_text), LENGTH(%s))) = LEFT(%s, LEAST(60, LENGTH(review_text), LENGTH(%s)))
                LIMIT 1;
                """,
                (tenant_id, competitor_id, review["author"], review["text"], review["text"], review["text"]),
            )
            existing = cursor.fetchone()
            if existing:
                review_id = str(existing[0])
                cursor.execute(
                    "UPDATE reviews SET like_count = GREATEST(COALESCE(like_count, 0), COALESCE(%s, 0)) "
                    "WHERE tenant_id = %s AND review_id = %s AND %s IS NOT NULL;",
                    (review["likes"], tenant_id, review_id, review["likes"]),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO reviews
                        (tenant_id, product_id, source_platform, reviewer_name, review_text, review_rating,
                         review_date, subject_type, competitor_id, source_status, collection_method,
                         source_id, external_review_id, safety_status, safety_flags, like_count)
                    VALUES (%s, NULL, 'Google Places', %s, %s, %s, COALESCE(%s::timestamptz, NOW()),
                            'COMPETITOR', %s, 'ALLOWED', 'PUBLIC_API', %s, %s, %s, %s::jsonb, %s)
                    ON CONFLICT (tenant_id, source_id, external_review_id)
                        WHERE source_id IS NOT NULL AND external_review_id IS NOT NULL
                    DO UPDATE SET like_count = EXCLUDED.like_count, review_text = EXCLUDED.review_text
                    RETURNING review_id, (xmax = 0);
                    """,
                    (
                        tenant_id, review["author"], review["text"], review["rating"], review["published_at"], competitor_id,
                        source_id, "apify:" + review["external_id"], "QUARANTINED" if flags else "SAFE", json.dumps(flags), review["likes"],
                    ),
                )
                review_id, inserted = cursor.fetchone()
                review_id = str(review_id)
                new += 1 if inserted else 0
            if review["owner_reply"]:
                reply_flags = scan_external_text(review["owner_reply"])
                cursor.execute(
                    """
                    INSERT INTO reviews
                        (tenant_id, product_id, source_platform, reviewer_name, review_text, review_date, subject_type,
                         competitor_id, source_status, collection_method, source_id, external_review_id, safety_status,
                         safety_flags, parent_review_id)
                    VALUES (%s, NULL, 'Google Places', 'Owner', %s, COALESCE(%s::timestamptz, NOW()), 'COMPETITOR',
                            %s, 'ALLOWED', 'PUBLIC_API', %s, %s, %s, %s::jsonb, %s)
                    ON CONFLICT (tenant_id, source_id, external_review_id)
                        WHERE source_id IS NOT NULL AND external_review_id IS NOT NULL
                    DO NOTHING;
                    """,
                    (
                        tenant_id, review["owner_reply"], review["owner_reply_at"], competitor_id, source_id,
                        "apify:" + review["external_id"] + ":owner", "QUARANTINED" if reply_flags else "SAFE",
                        json.dumps(reply_flags), review_id,
                    ),
                )
    conn.commit()
    return new, len(reviews)


# --------------------------------------------------------------------------- news

def _save_news(conn, tenant_id: str, competitor_id: str, items: list, source_kind: str) -> int:
    """Stores news about this competitor in market_news (an article already stored is left as it is).
    Returns how many were new."""
    added = 0
    with conn.cursor() as cursor:
        for item in items:
            cursor.execute(
                """
                INSERT INTO market_news (tenant_id, url, title, source_domain, language, published_at, topic,
                                         global_competitor_id, source_kind, summary)
                VALUES (%s, %s, %s, %s, NULL, %s::timestamptz, 'competitor', %s, %s, %s)
                ON CONFLICT (tenant_id, url) DO NOTHING;
                """,
                (tenant_id, item["url"][:2000], item["title"], item.get("source_domain"), item.get("published_at"),
                 competitor_id, source_kind, item.get("summary")),
            )
            added += cursor.rowcount
    conn.commit()
    return added


@credits.metered("competitor_enrichment")
def enrich_news(conn, tenant_id: str, competitor_id: str, competitor: dict) -> dict:
    status, reason_code, detail, items, confidence = _news_outcome(conn, tenant_id, competitor_id, competitor)
    _write_ledger(conn, tenant_id, competitor_id, FACET_NEWS, status, reason_code, detail, "news", items, confidence)
    return {"status": status, "reason_code": reason_code, "reason_detail": detail, "items_found": items}


def _news_outcome(conn, tenant_id, competitor_id, competitor):
    found, own_reason, web_state, confidence = 0, None, None, None

    website = competitor["website_url"]
    if not website:
        own_reason = NO_WEBSITE
    elif not is_public_http_url(website):
        own_reason = ROBOTS_DISALLOWED
    elif direct_search._robots_allowed_cached(website) is False:
        own_reason = ROBOTS_DISALLOWED
    else:
        items, own_reason = mentions.read_own_site_news(website)
        if items:
            _save_news(conn, tenant_id, competitor_id, items, "own_site")
            found += len(items)
            confidence = 1.0

    try:
        web_items = mentions.web_news(competitor["name"], None)
        web_state = "ok"
        if web_items:
            _save_news(conn, tenant_id, competitor_id, web_items, "web_search")
            found += len(web_items)
            confidence = 0.6 if confidence is None else confidence
    except web_search.SearchFailed as exc:
        web_state = str(exc)  # "not_configured" | "unreachable"

    if found:
        return STATUS_SUCCEEDED, None, None, found, confidence
    if web_state == "ok":
        return STATUS_FAILED, NO_NEWS, "No recent news naming this competitor was found.", 0, None
    if web_state == "unreachable":
        return STATUS_FAILED, PROVIDER_ERROR, "The news search could not be reached.", 0, None
    # No news search is set up (web_state == "not_configured"): only the competitor's own site could say.
    if own_reason == NO_FEED:
        return STATUS_FAILED, NO_FEED, "This competitor's website publishes no news feed, and no news search is set up.", 0, None
    if own_reason == SITE_UNREACHABLE:
        return STATUS_FAILED, SITE_UNREACHABLE, "The website could not be read, and no news search is set up.", 0, None
    if own_reason == ROBOTS_DISALLOWED:
        return STATUS_BLOCKED, ROBOTS_DISALLOWED, "The website does not allow automated reading, and no news search is set up.", 0, None
    return (STATUS_BLOCKED, NO_CREDENTIALS,
            "No news search provider is configured (BRAVE_SEARCH_API_KEY, TAVILY_API_KEY or SEARXNG_INSTANCE_URL) and this competitor has no website feed.",
            0, None)


# ----------------------------------------------------------------- video comments

def _save_comments(conn, tenant_id: str, competitor_id: str, source_id: str, platform: str, comments: list) -> int:
    """Stores comments as competitor reviews: top-level first, replies linked to their parent. Likes are
    kept as like_count (people agreeing). Returns how many were new."""
    new = 0
    ids = {}
    ordered = [c for c in comments if not c["parent_external_id"]] + [c for c in comments if c["parent_external_id"]]
    with conn.cursor() as cursor:
        for comment in ordered:
            parent = ids.get(comment["parent_external_id"]) if comment["parent_external_id"] else None
            if comment["parent_external_id"] and parent is None:
                continue  # a reply whose comment was not stored cannot be linked
            flags = scan_external_text(comment["text"])
            cursor.execute(
                """
                INSERT INTO reviews
                    (tenant_id, product_id, source_platform, reviewer_name, review_text, review_date, subject_type,
                     competitor_id, source_status, collection_method, source_id, external_review_id, safety_status,
                     safety_flags, like_count, reply_count, parent_review_id)
                VALUES (%s, NULL, %s, %s, %s, COALESCE(%s::timestamptz, NOW()), 'COMPETITOR', %s, 'ALLOWED', 'PUBLIC_API',
                        %s, %s, %s, %s::jsonb, %s, %s, %s)
                ON CONFLICT (tenant_id, source_id, external_review_id)
                    WHERE source_id IS NOT NULL AND external_review_id IS NOT NULL
                DO UPDATE SET like_count = EXCLUDED.like_count, reply_count = EXCLUDED.reply_count
                RETURNING review_id, (xmax = 0);
                """,
                (
                    tenant_id, platform, comment["author"], comment["text"], comment["published_at"], competitor_id,
                    source_id, comment["external_id"], "QUARANTINED" if flags else "SAFE", json.dumps(flags),
                    comment["likes"], comment["reply_count"], parent,
                ),
            )
            review_id, inserted = cursor.fetchone()
            ids[comment["external_id"]] = str(review_id)
            new += 1 if inserted else 0
    conn.commit()
    return new


@credits.metered("competitor_enrichment")
def enrich_comments(conn, tenant_id: str, competitor_id: str, competitor: dict, actor_user_id: Optional[str] = None) -> dict:
    status, reason_code, detail, items, confidence = _comments_outcome(conn, tenant_id, competitor_id, competitor, actor_user_id)
    _write_ledger(conn, tenant_id, competitor_id, FACET_COMMENTS, status, reason_code, detail, "youtube", items, confidence)
    return {"status": status, "reason_code": reason_code, "reason_detail": detail, "items_found": items}


def _comments_outcome(conn, tenant_id, competitor_id, competitor, actor_user_id):
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        return STATUS_BLOCKED, NO_CREDENTIALS, "YOUTUBE_API_KEY is not set for the service that collects comments.", 0, None
    approval = os.getenv("EXTERNAL_COMMENTS_APPROVAL_REFERENCE", "").strip()
    if not approval:
        return (STATUS_BLOCKED, PLATFORM_APPROVAL_MISSING,
                "The operator has not recorded approval to store public comments (EXTERNAL_COMMENTS_APPROVAL_REFERENCE).", 0, None)
    actor = actor_user_id or os.getenv("SCRAPER_ACTOR_USER_ID") or os.getenv("AI_SERVICE_ACTOR_USER_ID")
    if not actor:
        return STATUS_FAILED, SERVICE_MISCONFIGURED, "No acting user is configured for this service (SCRAPER_ACTOR_USER_ID).", 0, None
    try:
        comments = mentions.youtube_comments(competitor["name"], competitor["city"], api_key)
    except mentions.SourceError as exc:
        return STATUS_FAILED, exc.code, exc.detail, 0, None
    if not comments:
        return STATUS_FAILED, NO_VIDEOS, "No video naming this competitor, with public comments, was found.", 0, None
    source_id = _review_source(conn, tenant_id, actor, approval, name="YouTube comments (official API)",
                               collector_key="youtube_comments", retention_days=30)
    new = _save_comments(conn, tenant_id, competitor_id, source_id, "YouTube", comments)
    if new:
        _request_sentiment_analysis(tenant_id)
    return STATUS_SUCCEEDED, None, None, len(comments), 0.7


def enrich_prices(conn, tenant_id: str, competitor_id: str, competitor: dict, deep: bool = False) -> dict:
    """Re-reads the competitor's website - page text, structured data and menu
    PDFs / pictures (OCR) - and records the outcome with a specific reason.
    deep=True is "load more": more pages, items and menu files. Additive: a
    read that could not open the menu files keeps what an earlier read got
    from them (competitor_intel.save_site_intel)."""
    status, reason_code, detail, items, confidence = _prices_outcome(conn, tenant_id, competitor_id, competitor, deep)
    _write_ledger(conn, tenant_id, competitor_id, FACET_PRICES, status, reason_code, detail, "own_website", items, confidence)
    return {"status": status, "reason_code": reason_code, "reason_detail": detail, "items_found": items}


# intel.collect statuses that are a site-side outcome, not a bug: (ledger status, reason, owner-facing text).
_PRICE_READ_OUTCOMES = {
    "blocked_by_robots": (STATUS_BLOCKED, ROBOTS_DISALLOWED, "The website does not allow automated reading."),
    "unreachable": (STATUS_FAILED, SITE_UNREACHABLE, "The website could not be reached."),
    "http_error": (STATUS_FAILED, SITE_UNREACHABLE, "The website answered with an error."),
    "not_public": (STATUS_BLOCKED, SITE_UNREACHABLE, "The website address is not a public site."),
    "needs_javascript": (STATUS_FAILED, JS_RENDERED, "The prices are drawn by JavaScript and no headless browser is available to read them."),
    "no_relevant_page": (STATUS_FAILED, NO_PRICES_PUBLISHED, "No menu, price or product page was found on the website."),
    "no_price_published": (STATUS_FAILED, NO_PRICES_PUBLISHED, "The website lists no prices."),
    "not_own_site": (STATUS_BLOCKED, NOT_OWN_SITE, "The listed link is a directory or profile page, not the business's own website."),
    "other_business_site": (STATUS_BLOCKED, NOT_OWN_SITE, "The listed website belongs to a different business."),
    "extraction_failed": (STATUS_FAILED, PROVIDER_ERROR, "Reading the website failed unexpectedly."),
}


def _prices_outcome(conn, tenant_id, competitor_id, competitor, deep):
    if not competitor["website_url"]:
        return STATUS_NOT_APPLICABLE, NO_WEBSITE, "No website to read prices from.", 0, None
    from functools import partial

    from src.ai.market_inputs import competitor_intel
    from src.market_scraper.market_discovery import intel

    outcome = competitor_intel.refresh_competitor(conn, tenant_id, competitor_id, collect=partial(intel.collect, deep=deep))
    media = outcome.get("media") or {}
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*), AVG(confidence), COUNT(*) FILTER (WHERE COALESCE((payload->>'source_media')::boolean, FALSE)) "
            "FROM competitor_intel WHERE tenant_id = %s AND global_competitor_id = %s AND kind = 'product' AND payload ? 'price';",
            (tenant_id, competitor_id),
        )
        priced, average, from_menus = cursor.fetchone()
    confidence = round(float(average), 3) if average is not None else None
    notes = []
    if from_menus:
        notes.append(f"{from_menus} of them were read from menu files (PDF text or picture OCR) and are less certain than the page text.")
    if media.get("skipped_no_ocr"):
        notes.append(f"{media['skipped_no_ocr']} menu picture(s) were found but not read because the OCR engine is not installed on the server.")
    if priced:
        note = " ".join(notes) or None
        return (STATUS_PARTIAL if media.get("skipped_no_ocr") else STATUS_SUCCEEDED), None, note, priced, confidence
    known = _PRICE_READ_OUTCOMES.get(outcome.get("status"))
    if media.get("skipped_no_ocr"):
        return (STATUS_FAILED, OCR_NOT_AVAILABLE,
                f"The menu is published as {media['skipped_no_ocr']} picture(s) but the OCR engine is not installed on the server.", 0, None)
    if known:
        status, code, text = known
        return status, code, text, 0, None
    return STATUS_FAILED, NO_PRICES_PUBLISHED, "No prices were found on the website.", 0, None


def _recent_attempt_wait(conn, tenant_id: str, competitor_id: str, facet: str) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT last_attempt_at FROM competitor_enrichment "
            "WHERE tenant_id = %s AND global_competitor_id = %s AND facet = %s;",
            (tenant_id, competitor_id, facet),
        )
        row = cursor.fetchone()
    if not row or not row[0]:
        return 0
    elapsed = (datetime.now(timezone.utc) - row[0]).total_seconds()
    return max(0, int(MIN_SECONDS_BETWEEN_ATTEMPTS - elapsed))


@credits.metered("competitor_enrichment")
def enrich_competitor(
    conn, tenant_id: str, competitor_id: str, facets=None, places_api_key: Optional[str] = None,
    throttle: bool = False, actor_user_id: Optional[str] = None, deep: bool = False,
) -> dict:
    """Runs the requested facets (default: all enrichable ones) for one
    competitor and returns {facet: outcome}. Never raises for a provider or
    site problem - those are recorded in the ledger. Raises ValueError for an
    unknown competitor/facet. Re-scores the competitor afterwards when the
    profile changed, so a better profile can raise its confidence.

    throttle=True (manual retries) refuses to re-run a facet attempted within
    MIN_SECONDS_BETWEEN_ATTEMPTS and reports THROTTLED for it instead.
    deep=True ("load more") makes PRICES read more pages, items and menu files."""
    requested = tuple(facets) if facets else ENRICHABLE_FACETS
    unsupported = [facet for facet in requested if facet not in ENRICHABLE_FACETS]
    if unsupported:
        raise ValueError(f"facets not collectable yet: {unsupported}; supported: {list(ENRICHABLE_FACETS)}")
    competitor = _load_competitor(conn, tenant_id, competitor_id)
    if competitor is None:
        raise ValueError("competitor not found for this tenant")
    api_key = places_api_key or os.getenv("GOOGLE_PLACES_API_KEY") or None

    results: dict = {}
    profile_changed = False
    context: dict = {}  # PROFILE's Places Details, reused by REVIEWS so one call serves both
    for facet in ENRICHABLE_FACETS:  # fixed order: PROFILE first - it supplies the website and place id the others read
        if facet not in requested:
            continue
        wait = _recent_attempt_wait(conn, tenant_id, competitor_id, facet) if throttle else 0
        if wait:
            results[facet] = {"status": "THROTTLED", "retry_after_seconds": wait}
            continue
        try:
            if facet == FACET_PROFILE:
                results[facet] = enrich_profile(conn, tenant_id, competitor_id, competitor, api_key, context)
                profile_changed = results[facet]["status"] in (STATUS_SUCCEEDED, STATUS_PARTIAL)
                competitor = _load_competitor(conn, tenant_id, competitor_id) or competitor
            elif facet == FACET_REVIEWS:
                results[facet] = enrich_reviews(conn, tenant_id, competitor_id, competitor, api_key, context, actor_user_id)
            elif facet == FACET_NEWS:
                results[facet] = enrich_news(conn, tenant_id, competitor_id, competitor)
            elif facet == FACET_COMMENTS:
                results[facet] = enrich_comments(conn, tenant_id, competitor_id, competitor, actor_user_id)
            elif facet == FACET_PRICES:
                results[facet] = enrich_prices(conn, tenant_id, competitor_id, competitor, deep)
            else:
                results[facet] = enrich_social_links(conn, tenant_id, competitor_id, competitor)
        except Exception as exc:  # noqa: BLE001 - one facet failing must not stop the rest
            conn.rollback()
            logger.exception("enrichment %s failed for competitor %s", facet, competitor_id)
            _write_ledger(conn, tenant_id, competitor_id, facet, STATUS_FAILED, PROVIDER_ERROR, f"{type(exc).__name__}", None, 0, None)
            results[facet] = {"status": STATUS_FAILED, "reason_code": PROVIDER_ERROR, "reason_detail": type(exc).__name__, "items_found": 0}

    if profile_changed:
        try:
            from src.ai.pricing.competitor_classification import classify_competitor
            classify_competitor(conn, tenant_id, competitor_id)
        except Exception:  # noqa: BLE001 - a re-score problem must not undo collected data
            conn.rollback()
            logger.exception("re-score after enrichment failed for competitor %s", competitor_id)
    return results


_SETUP_BLOCK_CODES = (NO_CREDENTIALS, CREDENTIALS_REJECTED)

_DUE_CONDITION = """ce.facet IS NULL
                     OR (ce.status IN ('FAILED', 'PARTIAL', 'PENDING') AND ce.next_retry_at IS NOT NULL AND ce.next_retry_at <= NOW())"""
# "force": the owner asked to retry everything that is not done - including a
# facet blocked on a missing/rejected key (they may have just fixed it), but
# never a facet that needs a different human action (robots, no website).
_FORCE_CONDITION = """ce.facet IS NULL
                     OR ce.status IN ('FAILED', 'PARTIAL', 'PENDING')
                     OR (ce.status = 'BLOCKED' AND ce.reason_code IN ('NO_CREDENTIALS', 'CREDENTIALS_REJECTED', 'PLATFORM_APPROVAL_MISSING'))"""


@credits.metered("competitor_enrichment")
def enrich_tenant_competitors(
    conn, tenant_id: str, limit: Optional[int] = None, places_api_key: Optional[str] = None,
    mode: str = "due",
) -> dict:
    """Enriches this tenant's tracked competitors that still need it, best
    confidence first, capped by limit so one run has a bounded paid-API cost.

    mode="due" (discovery pass and the scheduled sweep): never attempted, or a
    transient failure whose scheduled retry time has passed. A permanent miss
    (NO_MATCH, NO_SOCIAL_LINKS) is NOT re-tried automatically - that would
    spend the same API calls forever for the same answer.
    mode="force" (owner's "retry all failed"): additionally every FAILED /
    PARTIAL / PENDING facet regardless of schedule, and facets blocked only by
    a missing or rejected key. SUCCEEDED and human-action blocks stay alone."""
    if mode not in ("due", "force"):
        raise ValueError("mode must be 'due' or 'force'")
    if limit is None:
        limit = int(os.getenv("ENRICHMENT_MAX_BULK" if mode == "force" else "ENRICHMENT_MAX_PER_RUN", "200" if mode == "force" else "50"))
    condition = _FORCE_CONDITION if mode == "force" else _DUE_CONDITION
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT tc.global_competitor_id
            FROM tenant_competitors tc
            JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
            WHERE tc.tenant_id = %s AND tc.is_tracked = TRUE
              AND gc.visibility = 'PRIVATE' AND gc.added_by_tenant_id = %s
              AND EXISTS (
                  SELECT 1 FROM unnest(ARRAY['PROFILE', 'SOCIAL_LINKS', 'REVIEWS', 'NEWS']) AS f(facet)
                  LEFT JOIN competitor_enrichment ce
                    ON ce.tenant_id = tc.tenant_id AND ce.global_competitor_id = tc.global_competitor_id AND ce.facet = f.facet
                  WHERE {condition}
              )
            ORDER BY tc.confidence_score DESC NULLS LAST, gc.competitor_name ASC
            LIMIT %s;
            """,
            (tenant_id, tenant_id, limit),
        )
        competitor_ids = [str(row[0]) for row in cursor.fetchall()]

    attempted = 0
    outcomes: dict = {}
    for competitor_id in competitor_ids:
        try:
            results = enrich_competitor(conn, tenant_id, competitor_id, facets=ROUTINE_FACETS, places_api_key=places_api_key)
            attempted += 1
            for result in results.values():
                outcomes[result["status"]] = outcomes.get(result["status"], 0) + 1
        except Exception:  # noqa: BLE001
            conn.rollback()
            logger.exception("enrichment failed for competitor %s", competitor_id)
    return {"competitors_attempted": attempted, "candidates": len(competitor_ids), "outcomes": outcomes}


# --------------------------------------------------------------------------
# Reporting: the data-completeness view the dashboard shows
# --------------------------------------------------------------------------

_POLICY_RANK = {"ALLOWED": 3, "RESTRICTED": 2, "BLOCKED": 1}


def _facet(status, reason_code=None, reason_detail=None, items=0, confidence=None, last_attempt=None, can_retry=False, action=None, action_source_ids=None) -> dict:
    """`action` names the fix the UI can offer for this gap (today:
    "review_source" - the owner/admin terms review at
    POST /competitors/sources/{source_id}/review, for each id in
    `action_source_ids`); None when there is nothing the owner can click."""
    return {
        "status": status, "reason_code": reason_code, "reason_detail": reason_detail,
        "items_found": items, "confidence": confidence,
        "last_attempt_at": last_attempt.isoformat() if last_attempt else None, "can_retry": can_retry,
        "action": action, "action_source_ids": action_source_ids or [],
    }


def _completeness_score(facets: dict) -> int:
    points = sum(1.0 if f["status"] == STATUS_SUCCEEDED else 0.5 if f["status"] == STATUS_PARTIAL else 0.0 for f in facets.values())
    return round(points / len(ALL_FACETS) * 100)


def load_data_completeness(conn, tenant_id: str, competitor_id: Optional[str] = None) -> dict:
    """{competitor_id: {"score": 0-100, "facets": {FACET: {...}}}} for every
    competitor of this tenant (or just competitor_id). Bulk queries only - no
    per-competitor round trips, so the dashboard stays cheap."""
    scope = "AND tc.global_competitor_id = %s" if competitor_id else ""
    scope_args = (competitor_id,) if competitor_id else ()
    with conn.cursor() as cursor:
        cursor.execute(
            f"SELECT tc.global_competitor_id, gc.website_url, gc.social_profiles, gc.address, gc.rating "
            f"FROM tenant_competitors tc JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id "
            f"WHERE tc.tenant_id = %s {scope};",
            (tenant_id,) + scope_args,
        )
        competitors = {str(r[0]): {"website": r[1], "social": r[2] or {}, "address": r[3], "rating": r[4]} for r in cursor.fetchall()}
        if not competitors:
            return {}

        cursor.execute(
            "SELECT global_competitor_id, facet, status, reason_code, reason_detail, items_found, data_confidence, last_attempt_at "
            "FROM competitor_enrichment WHERE tenant_id = %s;",
            (tenant_id,),
        )
        ledger = {(str(r[0]), r[1]): r[2:] for r in cursor.fetchall()}

        cursor.execute(
            "SELECT cpm.global_competitor_id, COUNT(cpr.competitor_price_id) "
            "FROM competitor_product_mappings cpm "
            "LEFT JOIN competitor_prices cpr ON cpr.tenant_id = cpm.tenant_id AND cpr.mapping_id = cpm.mapping_id "
            "WHERE cpm.tenant_id = %s AND cpm.is_active = TRUE GROUP BY cpm.global_competitor_id;",
            (tenant_id,),
        )
        price_counts = {str(r[0]): r[1] for r in cursor.fetchall()}

        cursor.execute(
            "SELECT DISTINCT cpm.global_competitor_id, ds.policy_status, ds.source_id FROM competitor_product_mappings cpm "
            "JOIN data_sources ds ON ds.tenant_id = cpm.tenant_id AND ds.source_id = cpm.source_id "
            "WHERE cpm.tenant_id = %s AND cpm.is_active = TRUE AND ds.is_active = TRUE;",
            (tenant_id,),
        )
        policies: dict = {}
        restricted_sources: dict = {}
        for cid, policy_status, source_id in cursor.fetchall():
            policies.setdefault(str(cid), set()).add(policy_status)
            if policy_status == "RESTRICTED":
                restricted_sources.setdefault(str(cid), []).append(str(source_id))

        cursor.execute(
            "SELECT competitor_id, COUNT(*) FROM reviews WHERE tenant_id = %s AND subject_type = 'COMPETITOR' GROUP BY competitor_id;",
            (tenant_id,),
        )
        review_counts = {str(r[0]): r[1] for r in cursor.fetchall()}

        cursor.execute(
            "SELECT global_competitor_id, COUNT(*) FROM market_news WHERE tenant_id = %s AND global_competitor_id IS NOT NULL "
            "GROUP BY global_competitor_id;",
            (tenant_id,),
        )
        news_counts = {str(r[0]): r[1] for r in cursor.fetchall()}

    result = {}
    for cid, info in competitors.items():
        facets = {}
        for facet in ENRICHABLE_FACETS:
            row = ledger.get((cid, facet))
            if facet == FACET_PRICES:
                continue  # derived below, from matched prices, the source policy and (when present) this ledger row
            if facet == FACET_REVIEWS and review_counts.get(cid, 0):
                # Reviews exist (from Places or any other collector): the data wins over a stale ledger status.
                last = row[5] if row else None
                facets[facet] = _facet(STATUS_SUCCEEDED, items=review_counts[cid], confidence=row[4] if row else None, last_attempt=last, can_retry=True)
            elif facet == FACET_NEWS and news_counts.get(cid, 0):
                # News exists (from any source, including the industry scan): the data wins over a stale ledger status.
                facets[facet] = _facet(STATUS_SUCCEEDED, items=news_counts[cid], confidence=row[4] if row else None,
                                       last_attempt=row[5] if row else None, can_retry=True)
            elif row:
                status, code, detail, items, confidence, last_attempt = row
                facets[facet] = _facet(status, code, detail, items, confidence, last_attempt, can_retry=status != STATUS_NOT_APPLICABLE)
            elif facet == FACET_PROFILE and info["address"] and info["rating"] is not None:
                facets[facet] = _facet(STATUS_SUCCEEDED, items=2, can_retry=True)  # filled by discovery itself
            else:
                facets[facet] = _facet(STATUS_PENDING, NOT_ATTEMPTED, "Not collected yet.", can_retry=True)

        prices = price_counts.get(cid, 0)
        statuses = policies.get(cid, set())
        if prices:
            facets[FACET_PRICES] = _facet(STATUS_SUCCEEDED, items=prices, can_retry=True)
        elif not info["website"]:
            facets[FACET_PRICES] = _facet(STATUS_NOT_APPLICABLE, NO_WEBSITE, "No website to read prices from.")
        elif ledger.get((cid, FACET_PRICES)) and not statuses:
            # A website read (including menu files) was attempted and said why it found nothing: that reason is
            # more specific than the generic "no product matched yet".
            status, code, detail, items, confidence, last_attempt = ledger[(cid, FACET_PRICES)]
            facets[FACET_PRICES] = _facet(status, code, detail, items, confidence, last_attempt, can_retry=True)
        elif not statuses:
            facets[FACET_PRICES] = _facet(STATUS_BLOCKED, NO_PRODUCTS_MAPPED, "None of your products has been matched on this competitor's site yet.")
        elif "ALLOWED" in statuses:
            facets[FACET_PRICES] = _facet(STATUS_FAILED, NO_DATA_COLLECTED, "Collection is approved but no price has been collected yet.")
        elif "RESTRICTED" in statuses:
            facets[FACET_PRICES] = _facet(
                STATUS_BLOCKED, TERMS_UNREVIEWED, "The site's terms have not been reviewed, so prices are not collected.",
                action=ACTION_REVIEW_SOURCE, action_source_ids=sorted(restricted_sources.get(cid, [])),
            )
        else:
            facets[FACET_PRICES] = _facet(STATUS_BLOCKED, ROBOTS_DISALLOWED, "The site disallows automated collection.")

        # Social content: only meaningful once links exist; collection itself is a later phase.
        facets[FACET_SOCIAL_CONTENT] = (
            _facet(STATUS_PENDING, COLLECTOR_NOT_ENABLED, "Social content collection is not enabled yet.") if info["social"]
            else _facet(STATUS_BLOCKED, NO_SOCIAL_LINKS, "No social profile is known for this competitor.")
        )
        result[cid] = {"score": _completeness_score(facets), "facets": facets}
    return result

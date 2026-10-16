"""
Competitor discovery for one company, from start to stored result.

1. Build the query from the company's own profile: industry (chosen, or
   read from its business type / products), location and radius, the
   search words for that industry in English and Arabic, and its top
   product categories.
2. Ask every configured source in parallel (OpenStreetMap, Google Places,
   web search, Apify). A source that isn't configured or is unreachable is
   reported as such; nothing is made up to fill the gap.
3. Merge reports of the same business, drop the company itself, score
   each business for relevance and confidence, and drop the irrelevant.
4. Store one competitor per business with every source it came from
   (competitor_sources), refresh ones already known, and start tracking the
   strongest new ones within the plan's tracked-competitor limit.

Each run is a discovery_runs row, so the screen can show progress and
what each source returned.
"""
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from src.market_scraper.category_taxonomy import categorize_catalog
from src.market_scraper.market_discovery import enrich, geocode, industries, matching, news, offerings, scoring
from src.market_scraper.market_discovery import relevance as relevance_rules
from src.market_scraper.market_discovery.models import DiscoveryQuery, ProviderResult
from src.market_scraper.market_discovery.providers import apify_maps, google_places, osm, overture, place_search, web_search, wikidata

logger = logging.getLogger("KEEL_MARKET_DISCOVERY")
PROVIDERS = (osm, overture, place_search, wikidata, google_places, web_search, apify_maps)
AUTO_TRACK_MAX = int(os.getenv("DISCOVERY_AUTO_TRACK_MAX", "10"))
AUTO_TRACK_MIN_RELEVANCE = 0.6
AUTO_TRACK_MIN_CONFIDENCE = 0.5
MAX_RADIUS_KM = 30.0
STALE_RUN_MINUTES = 15
ARABIC_COUNTRIES = {"JO", "SA", "AE", "KW", "QA", "BH", "OM", "EG", "LB", "SY", "IQ", "PS", "YE", "MA", "DZ", "TN", "LY", "SD"}
MAP_SOURCES = {"openstreetmap", "overture", "nominatim", "photon", "google_places", "apify_google_maps"}


class DiscoveryBusy(Exception):
    """A run is already queued or running for this company."""

    def __init__(self, run_id):
        super().__init__(run_id)
        self.run_id = run_id


def provider_status() -> List[dict]:
    out = []
    for provider in PROVIDERS:
        ok, reason = provider.available()
        out.append({"provider": provider.NAME, "configured": ok, "reason": reason})
    return out


# --- 1. The query -----------------------------------------------------

def load_profile(conn, tenant_id: str) -> dict:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT business_name, business_type, industry_key, business_description, website_url, city, country_code,
                   latitude, longitude, default_search_radius_km, search_scope_level, preferred_language
            FROM companies WHERE tenant_id = %s;
            """,
            (tenant_id,),
        )
        row = cursor.fetchone()
        cursor.execute(
            """
            SELECT localized_text(p.product_name), localized_text(p.category)
            FROM products p WHERE p.tenant_id = %s AND p.deleted_at IS NULL
            ORDER BY p.created_at DESC LIMIT 300;
            """,
            (tenant_id,),
        )
        products = cursor.fetchall()
    if row is None:
        raise ValueError("company not found")
    keys = ("name", "business_type", "industry_key", "description", "website", "city", "country_code", "latitude",
            "longitude", "radius_km", "scope_level", "language")
    profile = dict(zip(keys, row))
    profile["product_names"] = [p[0] for p in products if p[0]]
    categories = {}
    for _, category in products:
        if category:
            categories[category] = categories.get(category, 0) + 1
    profile["top_categories"] = [c for c, _ in sorted(categories.items(), key=lambda kv: -kv[1])[:3]]
    return profile


def _unique(words):
    seen, out = set(), []
    for word in words:
        if word and word.lower() not in seen:
            seen.add(word.lower())
            out.append(word)
    return out


def build_query(tenant_id: str, profile: dict, radius_km: Optional[float] = None) -> DiscoveryQuery:
    industry, _how = industries.resolve(profile.get("industry_key"), profile.get("business_type"), profile.get("product_names") or [])
    if radius_km is None:
        if profile.get("scope_level") == "CUSTOM" and profile.get("radius_km"):
            radius_km = float(profile["radius_km"])  # the owner's own choice
        elif profile.get("scope_level") == "CITY" and profile.get("radius_km"):
            radius_km = min(float(profile["radius_km"]), industry.default_radius_km * 2 or MAX_RADIUS_KM)
        else:
            radius_km = industry.default_radius_km or 10.0
    radius_km = max(0.5, min(float(radius_km), MAX_RADIUS_KM))
    country = (profile.get("country_code") or "").upper() or None
    arabic = country in ARABIC_COUNTRIES or profile.get("language") == "ar"
    keywords = list(industry.keywords_en)
    if arabic:
        keywords = list(industry.keywords_ar[:2]) + keywords
    # The owner's own description, in whatever language they wrote it, is
    # always searched too - it is what their customers would type.
    own_words = re.sub(r"\s+", " ", profile.get("business_type") or "").strip()[:80]
    if own_words and len(own_words) >= 3:
        keywords.append(own_words)
    for category in profile.get("top_categories") or []:
        if category.lower() not in (k.lower() for k in keywords):
            keywords.append(category)
    return DiscoveryQuery(
        tenant_id=tenant_id, industry_key=industry.key, industry_label=industry.label_en,
        keywords=_unique(keywords)[:8], latitude=profile.get("latitude"), longitude=profile.get("longitude"),
        radius_km=radius_km, city=profile.get("city"), country_code=country,
        language="ar" if profile.get("language") == "ar" else "en",
        own_name=profile.get("name"), own_website=profile.get("website"),
        osm_tags=industry.osm_tags, google_types=industry.google_types,
        category_paths=tuple(categorize_catalog(profile.get("product_names") or [], profile.get("business_type"))),
    )


_CATEGORY_WORDS_CACHE: dict = {}


def with_category_words(query: DiscoveryQuery, ask=None) -> DiscoveryQuery:
    """A business type outside the industry list, described with no English
    word ("مكتب عقاري"), gets English category words ("real estate agent")
    so sources whose categories are English (Overture, map types) can match
    it. Asked once per description of the configured AI model; without one,
    the description's own words are still searched in names."""
    if query.industry_key != industries.CUSTOM or any(re.search(r"[a-z]{3}", k.lower()) for k in query.keywords):
        return query
    text = query.industry_label
    if text not in _CATEGORY_WORDS_CACHE:
        words = ()
        try:
            from src.ai.rag import llm_client

            if ask is None and not relevance_rules.ai_hints_enabled():
                raise LookupError("AI hints off")
            answer = (ask or llm_client.chat_completion)([
                {"role": "system", "content": "You name business categories. Answer with only a JSON list of 1 to 4 "
                                              "short lowercase English category names, e.g. [\"real estate agent\", \"property management\"]."},
                {"role": "user", "content": f"Business type: {text}"},
            ], temperature=0, max_tokens=500)
            listed = json.loads(re.search(r"\[.*\]", answer, re.S).group(0))
            words = tuple(w.strip().lower() for w in listed if isinstance(w, str) and re.fullmatch(r"[a-z][a-z &/-]{1,40}", w.strip().lower()))[:4]
        except Exception as exc:  # noqa: BLE001 - names are still searched without it
            logger.info("no English category words for %r: %s", text, type(exc).__name__)
        _CATEGORY_WORDS_CACHE[text] = words
    words = _CATEGORY_WORDS_CACHE[text]
    if not words:
        return query
    from dataclasses import replace

    # Only distinctive words of the categories: "estate", "property" - not
    # "real", "agent" or "management", which name many other trades.
    distinctive = tuple(w for phrase in words for w in re.split(r"[ &/-]+", phrase)
                        if len(w) >= 6 and w not in {"management", "services", "solutions", "general", "company"})
    return replace(query, category_words=distinctive,
                   keywords=_unique(list(query.keywords) + list(words))[:8])


# --- 2-3. Search, merge, score ----------------------------------------

def search_all(query: DiscoveryQuery, providers=PROVIDERS) -> List[ProviderResult]:
    with ThreadPoolExecutor(max_workers=len(providers)) as pool:
        futures = [pool.submit(p.search, query) for p in providers]
        results = []
        for provider, future in zip(providers, futures):
            try:
                results.append(future.result(timeout=240))
            except Exception as exc:  # noqa: BLE001 - one source failing never sinks the run
                logger.exception("provider %s crashed", provider.NAME)
                results.append(ProviderResult(provider.NAME, "failed", reason=type(exc).__name__))
    return results


# Placeholders mappers sometimes leave as a name, in the languages KEEL serves.
_PLACEHOLDER_NAMES = {"خاص", "private", "closed", "مغلق", "unknown", "no name", "test", "shop", "store", "محل"}


def _generic_name(name: str, query: DiscoveryQuery) -> bool:
    """A map entry named only "Bakery" or "حلويات" (or a placeholder such as
    "خاص" - "private") names no business anyone could compete with or look
    up - it isn't listed as a competitor."""
    text = re.sub(r"[^\w\u0600-\u06ff]+", " ", (name or "").lower()).strip()
    return (not text or text in _PLACEHOLDER_NAMES or text in industries.trade_words()
            or text in {(k or "").lower().strip() for k in query.keywords or []})


def rank(query: DiscoveryQuery, results: List[ProviderResult]):
    candidates = [c for r in results for c in r.candidates if not _generic_name(c.name, query)]
    scored = []
    for entity in matching.merge(candidates):
        if matching.is_self(entity, query.own_name, query.own_website):
            continue
        relevance, confidence, nearest, reasons = scoring.score(entity, query)
        if relevance < scoring.MIN_RELEVANCE:
            continue
        if nearest is not None and nearest > query.radius_km * 1.5 and (industries.get(query.industry_key) or industries.get(industries.CUSTOM)).local:
            continue
        scored.append((entity, relevance, confidence, nearest, reasons))
    return _classify(query, scored)[:query.max_results]


def _classify(query: DiscoveryQuery, scored):
    """Relationship of each business (relevance.py), with a second pass: the
    specific categories shared by businesses whose name shows the company's
    specialty (middle_eastern_restaurant, doner_kebab_restaurant for a
    shawarma/mansaf restaurant) mark the others in those categories as
    direct too - learnt from the market itself, for any industry."""
    first = []
    for entity, relevance, confidence, nearest, reasons in scored:
        fit_reason = reasons[0]["code"] if reasons and reasons[0]["code"] != "distance" else None
        relationship, why = relevance_rules.classify(entity.name, entity.first("name_ar"), entity.categories(), fit_reason,
                                                     query, query.specialty_terms)
        first.append((entity, relevance, confidence, nearest, reasons, fit_reason, relationship, why))
    specialty = relevance_rules.specialty_categories(
        [(e.categories(), rel) for e, *_rest, rel, why in first if rel == relevance_rules.DIRECT
         and any(w.get("code") == "same_specialty" for w in why)], query)
    ranked = []
    for entity, relevance, confidence, nearest, reasons, fit_reason, relationship, why in first:
        if relationship == relevance_rules.INDIRECT and specialty:
            shared = specialty & relevance_rules.specific_categories(entity.categories(), query)
            if shared:
                relationship, why = relevance_rules.DIRECT, [{"code": "same_specialty", "term": sorted(shared)[0].replace("_", " "),
                                                              "where": "category"}]
        # A business in a different segment (a donut shop for a burger
        # restaurant) is not a competitor - unless it has stronger evidence:
        # the same products at a published price, or the company's own specialty.
        if relationship != relevance_rules.DIRECT and relevance_rules.in_different_category(
                entity.name, entity.first("name_ar"), entity.categories(), query):
            continue
        relevance = round(relevance_rules.adjusted_score(relevance, relationship), 4)
        codes = {w.get("code") for w in why}
        reasons = [{"code": "relationship", "value": relationship}] + why + [r for r in reasons if r.get("code") not in codes]
        ranked.append((entity, relevance, confidence, nearest, reasons))
    ranked.sort(key=lambda r: (-r[1], -r[2], r[3] if r[3] is not None else 1e9))
    return ranked


def rescore(query: DiscoveryQuery, ranked):
    """Scores again after enrichment added what businesses say about
    themselves, and drops any that turn out to be another kind of business."""
    scored = []
    for entity, *_old in ranked:
        relevance, confidence, nearest, reasons = scoring.score(entity, query)
        if relevance < scoring.MIN_RELEVANCE:
            continue
        scored.append((entity, relevance, confidence, nearest, reasons))
    return _classify(query, scored)


# --- 4. Store ---------------------------------------------------------

def _existing_competitor(cursor, tenant_id: str, entity) -> Optional[str]:
    for candidate in entity.candidates:
        cursor.execute(
            "SELECT global_competitor_id FROM competitor_sources WHERE tenant_id = %s AND source = %s AND source_ref = %s;",
            (tenant_id, _source_label(candidate.source), candidate.source_ref),
        )
        row = cursor.fetchone()
        if row:
            return str(row[0])
    for key in entity.domain_keys:
        cursor.execute(
            "SELECT global_competitor_id FROM global_competitors WHERE added_by_tenant_id = %s AND visibility = 'PRIVATE' AND website_identity_key = %s;",
            (tenant_id, key),
        )
        row = cursor.fetchone()
        if row:
            return str(row[0])
    cursor.execute(
        "SELECT global_competitor_id FROM global_competitors WHERE added_by_tenant_id = %s AND visibility = 'PRIVATE' AND LOWER(competitor_name) = LOWER(%s);",
        (tenant_id, entity.name),
    )
    row = cursor.fetchone()
    return str(row[0]) if row else None


def _source_label(source: str) -> str:
    return source


def _nearest_branch(entity):
    with_distance = [b for b in entity.branches if b.distance_km is not None]
    if with_distance:
        return min(with_distance, key=lambda b: b.distance_km)
    return entity.branches[0] if entity.branches else None


def store(conn, tenant_id: str, query: DiscoveryQuery, ranked) -> dict:
    now = datetime.now(timezone.utc)
    counts = {"new": 0, "updated": 0, "new_ids": []}
    industry = industries.get(query.industry_key)
    with conn.cursor() as cursor:
        for entity, relevance, confidence, nearest, reasons in ranked:
            branch = _nearest_branch(entity)
            website = entity.first("website")
            identity = next(iter(sorted(entity.domain_keys)), None)
            rating, reviews = entity.best_rating()
            details = {
                "name_ar": entity.first("name_ar"), "website": website, "identity": identity,
                "industry": query.industry_label or (industry.label_en if industry else None), "country": entity.first("country_code") or query.country_code,
                "city": entity.first("city"), "lat": branch.latitude if branch else None, "lon": branch.longitude if branch else None,
                "phone": entity.first("phone"), "address": branch.address if branch and branch.address else entity.first("address"),
                "categories": entity.categories(), "rating": rating, "reviews": reviews, "price_level": entity.first("price_level"),
            }
            competitor_id = _existing_competitor(cursor, tenant_id, entity)
            if competitor_id is None:
                cursor.execute("SAVEPOINT discovery_insert;")
                try:
                    cursor.execute(
                        """
                        INSERT INTO global_competitors (competitor_name, name_ar, website_url, website_identity_key, industry_sector,
                            visibility, added_by_tenant_id, country_code, city, latitude, longitude, phone, address, categories,
                            rating, review_count, price_level)
                        VALUES (%s, %s, %s, %s, %s, 'PRIVATE', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING global_competitor_id;
                        """,
                        (entity.name[:255], (details["name_ar"] or None) and details["name_ar"][:255], website, identity,
                         details["industry"], tenant_id, details["country"], details["city"], details["lat"], details["lon"],
                         details["phone"], details["address"], details["categories"], details["rating"], details["reviews"],
                         details["price_level"]),
                    )
                    competitor_id = str(cursor.fetchone()[0])
                    cursor.execute("RELEASE SAVEPOINT discovery_insert;")
                except Exception:  # noqa: BLE001 - a name/domain race with another row: reuse that row
                    cursor.execute("ROLLBACK TO SAVEPOINT discovery_insert;")
                    competitor_id = _existing_competitor(cursor, tenant_id, entity)
                    if competitor_id is None:
                        logger.warning("could not store competitor %r", entity.name)
                        continue
            else:
                cursor.execute(
                    """
                    UPDATE global_competitors SET
                        name_ar = COALESCE(name_ar, %s), website_url = COALESCE(website_url, %s),
                        website_identity_key = COALESCE(website_identity_key, %s), industry_sector = COALESCE(industry_sector, %s),
                        country_code = COALESCE(country_code, %s), city = COALESCE(city, %s),
                        latitude = COALESCE(%s, latitude), longitude = COALESCE(%s, longitude),
                        phone = COALESCE(%s, phone), address = COALESCE(%s, address),
                        categories = CASE WHEN cardinality(%s::text[]) > 0 THEN %s::text[] ELSE categories END,
                        rating = COALESCE(%s, rating), review_count = COALESCE(%s, review_count), price_level = COALESCE(%s, price_level)
                    WHERE global_competitor_id = %s AND added_by_tenant_id = %s;
                    """,
                    (details["name_ar"], website, identity, details["industry"], details["country"], details["city"],
                     details["lat"], details["lon"], details["phone"], details["address"], details["categories"],
                     details["categories"], details["rating"], details["reviews"], details["price_level"], competitor_id, tenant_id),
                )
            method = "MAP_LISTING" if entity.sources & MAP_SOURCES else "WEB_SEARCH"
            cursor.execute(
                """
                INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked, tier, discovery_method,
                    distance_km, relevance_score, confidence, source_count, branch_count, first_seen_at, last_seen_at,
                    match_reasons, competition_level, classified_at, relationship)
                VALUES (%s, %s, FALSE, 'CANDIDATE', %s, %s, %s, %s, %s, %s, %s, %s, %s, 'MARKET', %s, %s)
                ON CONFLICT (tenant_id, global_competitor_id) DO UPDATE SET
                    distance_km = EXCLUDED.distance_km, relevance_score = EXCLUDED.relevance_score,
                    confidence = EXCLUDED.confidence, source_count = EXCLUDED.source_count,
                    branch_count = EXCLUDED.branch_count, last_seen_at = EXCLUDED.last_seen_at,
                    first_seen_at = COALESCE(tenant_competitors.first_seen_at, EXCLUDED.first_seen_at),
                    match_reasons = EXCLUDED.match_reasons, classified_at = EXCLUDED.classified_at,
                    relationship = EXCLUDED.relationship
                RETURNING (xmax = 0);
                """,
                (tenant_id, competitor_id, method, nearest, relevance, confidence, len(entity.sources),
                 len(entity.branches), now, now, json.dumps(reasons), now, _relationship(reasons)),
            )
            inserted = cursor.fetchone()[0]
            if inserted:
                counts["new"] += 1
                counts["new_ids"].append((competitor_id, relevance, confidence))
            else:
                counts["updated"] += 1
            for candidate in entity.candidates:
                cursor.execute(
                    """
                    INSERT INTO competitor_sources (tenant_id, global_competitor_id, source, source_ref, source_url, payload)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, source, source_ref) DO UPDATE SET
                        last_seen_at = CURRENT_TIMESTAMP, source_url = EXCLUDED.source_url, payload = EXCLUDED.payload,
                        global_competitor_id = EXCLUDED.global_competitor_id;
                    """,
                    (tenant_id, competitor_id, _source_label(candidate.source), candidate.source_ref[:500], candidate.source_url,
                     json.dumps({"name": candidate.name, "address": candidate.address, "lat": candidate.latitude,
                                 "lon": candidate.longitude, "phone": candidate.phone, "website": candidate.website,
                                 "categories": candidate.categories[:8], "rating": candidate.rating,
                                 "reviews": candidate.review_count, **{k: v for k, v in candidate.raw.items() if k in ("title", "snippet", "social")}},
                                default=str)),
                )
    return counts


def _relationship(reasons) -> Optional[str]:
    return next((r["value"] for r in reasons or [] if r.get("code") == "relationship"), None)


def _score_competitors(conn, tenant_id: str) -> None:
    """Fills in each competitor's category, 0-100 competitive confidence and
    evidence record (competitor_classification.py). Re-scoring only: it never
    starts tracking anyone and never overturns an owner's choice. A failure
    here must not discard the discovery that already succeeded."""
    try:
        from src.market_scraper.discovery import refresh_tenant_competitors
        refresh_tenant_competitors(conn, tenant_id)
    except Exception:  # noqa: BLE001
        conn.rollback()
        logger.exception("could not score competitors for tenant %s", tenant_id)


def auto_track(conn, tenant_id: str, new_ids) -> int:
    """Starts tracking the strongest newly found competitors, within the
    plan's limit. Never untracks anything the owner chose, and never
    re-tracks anything the owner untracked."""
    from src.ai.core import usage

    feature = usage.get_plan(conn, tenant_id)["features"].get(usage.TRACKED_COMPETITORS)
    limit = feature["limit"] if feature else None
    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM tenant_competitors WHERE tenant_id = %s AND is_tracked;", (tenant_id,))
        tracked = cursor.fetchone()[0]
        room = AUTO_TRACK_MAX if limit is None else max(0, min(AUTO_TRACK_MAX, int(limit) - tracked))
        chosen = [cid for cid, relevance, confidence in sorted(new_ids, key=lambda r: (-r[1], -r[2]))
                  if relevance >= AUTO_TRACK_MIN_RELEVANCE and confidence >= AUTO_TRACK_MIN_CONFIDENCE][:room]
        started = 0
        for competitor_id in chosen:
            cursor.execute(
                "UPDATE tenant_competitors SET is_tracked = TRUE, tier = 'RELEVANT' WHERE tenant_id = %s AND global_competitor_id = %s "
                "AND tracking_decision IS DISTINCT FROM 'USER_UNTRACKED';",
                (tenant_id, competitor_id),
            )
            started += cursor.rowcount
    return started


# --- Runs -------------------------------------------------------------

def start_run(conn, tenant_id: str, user_id: Optional[str], radius_km: Optional[float] = None) -> str:
    """Queues a run (one active run per company). Caller commits."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE discovery_runs SET status = 'failed', error = 'timed_out', finished_at = CURRENT_TIMESTAMP
            WHERE tenant_id = %s AND status IN ('queued', 'running') AND created_at < %s;
            """,
            (tenant_id, datetime.now(timezone.utc) - timedelta(minutes=STALE_RUN_MINUTES)),
        )
        cursor.execute("SELECT run_id FROM discovery_runs WHERE tenant_id = %s AND status IN ('queued', 'running');", (tenant_id,))
        row = cursor.fetchone()
        if row:
            raise DiscoveryBusy(str(row[0]))
        cursor.execute(
            "INSERT INTO discovery_runs (tenant_id, requested_by, radius_km, query) VALUES (%s, %s, %s, %s) RETURNING run_id;",
            (tenant_id, user_id, radius_km, json.dumps({"radius_km": radius_km})),
        )
        return str(cursor.fetchone()[0])


def _update_run(conn, run_id: str, **fields) -> None:
    sets = ", ".join(f"{k} = %s" for k in fields)
    values = [json.dumps(v) if k in ("query", "providers") else v for k, v in fields.items()]
    with conn.cursor() as cursor:
        cursor.execute(f"UPDATE discovery_runs SET {sets} WHERE run_id = %s;", (*values, run_id))
    conn.commit()


def _failure_reason(query: DiscoveryQuery, results: List[ProviderResult]) -> str:
    # Sources that tried and couldn't be reached are the reason, even when
    # the city couldn't be placed on the map (geocoding needs them too).
    if any(r.status == "failed" for r in results):
        return "unreachable"
    if not query.has_location:
        # A city was given but couldn't be placed on the map, or nothing was given.
        return "location_not_found" if query.city else "no_location"
    return "no_sources"


def execute_run(conn, tenant_id: str, run_id: str, radius_km: Optional[float] = None, providers=PROVIDERS,
                site_reader=None, news_reader=None) -> dict:
    """Runs a queued discovery to completion on `conn` (a tenant connection).
    `site_reader` / `news_reader` replace intel.collect / news.collect (tests)."""
    _update_run(conn, run_id, status="running", started_at=datetime.now(timezone.utc))
    try:
        profile = load_profile(conn, tenant_id)
        if profile.get("latitude") is None and profile.get("city"):
            point = geocode.geocode_city(profile["city"], profile.get("country_code"))
            if point:
                profile["latitude"], profile["longitude"] = point
                with conn.cursor() as cursor:
                    cursor.execute(
                        "UPDATE companies SET latitude = %s, longitude = %s WHERE tenant_id = %s AND latitude IS NULL;",
                        (point[0], point[1], tenant_id),
                    )
        query = with_category_words(build_query(tenant_id, profile, radius_km))
        from dataclasses import replace as _replace
        query = _replace(query, specialty_terms=relevance_rules.specialty_terms(profile, query))
        results = search_all(query, providers)
        ranked = rank(query, results)
        # 3b. Read the strongest candidates' own websites, then score again.
        enriched = enrich.enrich(ranked)
        if enriched["read"]:
            ranked = rescore(query, ranked)
        counts = store(conn, tenant_id, query, ranked)
        tracked = auto_track(conn, tenant_id, counts["new_ids"])
        conn.commit()
        _score_competitors(conn, tenant_id)
        # 5. Read what the competitors publish on their own sites, then match
        #    their priced items to the company's own products.
        site_intel = _collect_site_intel(conn, tenant_id, site_reader, query.country_code)
        priced = _match_prices(conn, tenant_id, site_intel.get("competitor_ids") or [])
        # 6. Recent news about the industry and the tracked competitors.
        news_result = _collect_news(conn, tenant_id, query, news_reader)
        ok = [r for r in results if r.status == "ok"]
        status = "completed" if ok and all(r.status != "failed" for r in results) else ("partial" if ok else "failed")
        summary = {
            "status": status, "industry_key": query.industry_key,
            "center_latitude": query.latitude, "center_longitude": query.longitude, "radius_km": query.radius_km,
            "query": {"keywords": query.keywords, "city": query.city, "country_code": query.country_code},
            "providers": {r.provider: {"status": r.status, "reason": r.reason, "found": len(r.candidates), "requests": r.requests}
                          for r in results} | {"website": {"status": "ok" if enriched["checked"] else "skipped",
                                                           "reason": None, "found": enriched["read"],
                                                           "requests": enriched["checked"], "blocked": enriched["blocked"]},
                                                "website_intel": {"status": "ok" if site_intel["read"] else "skipped",
                                                                  "reason": None, "found": site_intel["read"],
                                                                  "requests": site_intel["pages_tried"]},
                                                "gdelt": {"status": news_result["status"], "reason": news_result.get("reason"),
                                                          "found": news_result.get("added", 0), "requests": news_result["requests"]}},
            "found_count": len(ranked), "new_count": counts["new"], "updated_count": counts["updated"],
            # Every search sent and page read, and how many of them answered.
            "sources_checked": sum(r.requests for r in results) + enriched["checked"] + site_intel["pages_tried"]
                               + news_result["requests"],
            "sources_answered": sum(r.requests for r in results if r.status == "ok") + enriched["read"] + site_intel["pages"]
                                + news_result["answered"],
            "tracked_count": tracked + priced["tracked"], "finished_at": datetime.now(timezone.utc),
            "coverage": json.dumps(_coverage(conn, tenant_id, results, ranked, site_intel, priced, news_result)),
            "error": None if ok else _failure_reason(query, results),
        }
        conn.commit()
        _update_run(conn, run_id, **summary)
        return summary
    except Exception as exc:
        conn.rollback()
        logger.exception("discovery run %s failed", run_id)
        _update_run(conn, run_id, status="failed", error=type(exc).__name__[:200], finished_at=datetime.now(timezone.utc))
        raise


def _collect_site_intel(conn, tenant_id: str, site_reader=None, country: Optional[str] = None) -> dict:
    """Never fails the run: competitors are already stored by now."""
    from src.ai.market_inputs import competitor_intel

    try:
        counts = competitor_intel.refresh_strongest(conn, tenant_id, country=country,
                                                    **({"collect": site_reader} if site_reader else {}))
        conn.commit()
    except Exception:  # noqa: BLE001
        conn.rollback()
        logger.exception("reading competitor websites failed for %s", tenant_id)
        counts = {"checked": 0, "read": 0, "pages": 0, "facts": 0, "products": 0, "prices": 0, "promotions": 0,
                  "statuses": {}, "competitor_ids": []}
    counts["pages_tried"] = max(counts["checked"], counts["pages"])
    return counts


def _match_prices(conn, tenant_id: str, competitor_ids: List[str], ask=None) -> dict:
    """Competitors whose sites were read: priced items matched to the company's
    products (offerings.py); a competitor selling the company's products is
    DIRECT, and is tracked (plan limit permitting) so its prices reach
    pricing, the dashboard and reports. Never fails the run."""
    out = {"competitors_matched": 0, "prices_matched": 0, "products_covered": 0, "currency_mismatch": 0, "tracked": 0,
           "examples": []}
    try:
        products = offerings.company_products(conn, tenant_id)
        covered = set()
        matched_ids = []
        for competitor_id in competitor_ids:
            result = offerings.record_matches(conn, tenant_id, competitor_id, products, ask=ask)
            out["currency_mismatch"] += result["currency_mismatch"]
            if not result["matched"]:
                continue
            matched_ids.append((competitor_id, result["matched"]))
            out["competitors_matched"] += 1
            out["prices_matched"] += result["matched"]
            covered.update(m["product_id"] for m in result["matches"])
            out["examples"].extend(result["matches"][:2])
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE tenant_competitors SET relationship = 'DIRECT', competition_level = 'PRODUCT',
                        match_reasons = jsonb_build_array(jsonb_build_object('code', 'relationship', 'value', 'DIRECT'),
                                                          jsonb_build_object('code', 'same_products', 'count', %s))
                                        || COALESCE((SELECT jsonb_agg(r) FROM jsonb_array_elements(match_reasons) r
                                                     WHERE r->>'code' NOT IN ('relationship', 'same_products')), '[]'::jsonb)
                    WHERE tenant_id = %s AND global_competitor_id = %s;
                    """,
                    (result["matched"], tenant_id, competitor_id),
                )
        out["products_covered"] = len(covered)
        out["tracked"] = _track_priced(conn, tenant_id, [cid for cid, _n in sorted(matched_ids, key=lambda m: -m[1])])
        out["examples"] = out["examples"][:8]
        conn.commit()
    except Exception:  # noqa: BLE001
        conn.rollback()
        logger.exception("matching competitor prices failed for %s", tenant_id)
    return out


def _track_priced(conn, tenant_id: str, competitor_ids: List[str]) -> int:
    from src.ai.core import usage

    if not competitor_ids:
        return 0
    feature = usage.get_plan(conn, tenant_id)["features"].get(usage.TRACKED_COMPETITORS)
    limit = feature["limit"] if feature else None
    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM tenant_competitors WHERE tenant_id = %s AND is_tracked;", (tenant_id,))
        tracked = cursor.fetchone()[0]
        room = len(competitor_ids) if limit is None else max(0, int(limit) - tracked)
        added = 0
        for competitor_id in competitor_ids:
            if added >= room:
                break
            cursor.execute(
                "UPDATE tenant_competitors SET is_tracked = TRUE, tier = 'RELEVANT' WHERE tenant_id = %s AND global_competitor_id = %s AND NOT is_tracked "
                "AND tracking_decision IS DISTINCT FROM 'USER_UNTRACKED';",
                (tenant_id, competitor_id),
            )
            added += cursor.rowcount
    return added


def _coverage(conn, tenant_id: str, results, ranked, site_intel: dict, priced: dict, news_result: dict) -> dict:
    """What the run produced at every stage - stored with the run and shown
    on the Competitors page, so a big number of names is never mistaken for
    usable intelligence."""
    raw = sum(len(r.candidates) for r in results)
    entities = len(matching.merge([c for r in results for c in r.candidates])) if raw else 0
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COALESCE(relationship, 'UNCLASSIFIED'), COUNT(*), COUNT(*) FILTER (WHERE gc.website_url IS NOT NULL)
            FROM tenant_competitors tc JOIN global_competitors gc USING (global_competitor_id)
            WHERE tc.tenant_id = %s GROUP BY 1;
            """,
            (tenant_id,),
        )
        by_relationship = {k: {"count": n, "with_website": w} for k, n, w in cursor.fetchall()}
    return {
        "listings_found": raw,
        "duplicates_merged": max(0, raw - entities),
        "businesses": entities,
        "relevant_saved": len(ranked),
        "by_relationship": by_relationship,
        "websites": {"tried": site_intel.get("checked", 0), "read": site_intel.get("read", 0),
                     "pages_read": site_intel.get("pages", 0), "outcomes": site_intel.get("statuses", {})},
        "products_found": site_intel.get("products", 0),
        "prices_found": site_intel.get("prices", 0),
        "promotions_found": site_intel.get("promotions", 0),
        "prices_matched": priced.get("prices_matched", 0),
        "products_with_competitor_prices": priced.get("products_covered", 0),
        "competitors_with_matched_prices": priced.get("competitors_matched", 0),
        "examples": priced.get("examples", []),
        "news": {"status": news_result.get("status"), "added": news_result.get("added", 0)},
    }


def _collect_news(conn, tenant_id: str, query: DiscoveryQuery, news_reader=None) -> dict:
    """Never fails the run either."""
    from src.ai.market_inputs import market_news

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT gc.competitor_name FROM tenant_competitors tc
                JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
                WHERE tc.tenant_id = %s ORDER BY tc.is_tracked DESC, tc.relevance_score DESC NULLS LAST LIMIT 6;
                """,
                (tenant_id,),
            )
            names = [r[0] for r in cursor.fetchall()]
        industry = industries.get(query.industry_key)
        terms = list(industry.keywords_en[:3]) + list(industry.keywords_ar[:2]) if industry else []
        terms = terms or list(query.keywords[:4])  # a business type outside the table: its own words
        result = (news_reader or news.collect)(terms, names, query.country_code)
        result["added"] = market_news.save(conn, tenant_id, result["articles"])
        conn.commit()
        return result
    except Exception:  # noqa: BLE001
        conn.rollback()
        logger.exception("news collection failed for %s", tenant_id)
        return {"articles": [], "requests": 0, "answered": 0, "status": "failed", "reason": "unreachable", "added": 0}


def get_run(conn, tenant_id: str, run_id: Optional[str] = None) -> Optional[dict]:
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT run_id, status, industry_key, center_latitude, center_longitude, radius_km, query, providers,
                   found_count, new_count, updated_count, tracked_count, error, created_at, started_at, finished_at,
                   sources_checked, sources_answered, coverage
            FROM discovery_runs WHERE tenant_id = %s {"AND run_id = %s" if run_id else ""}
            ORDER BY created_at DESC LIMIT 1;
            """,
            (tenant_id, run_id) if run_id else (tenant_id,),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    keys = ("run_id", "status", "industry_key", "center_latitude", "center_longitude", "radius_km", "query", "providers",
            "found_count", "new_count", "updated_count", "tracked_count", "error", "created_at", "started_at", "finished_at",
            "sources_checked", "sources_answered", "coverage")
    run = dict(zip(keys, row))
    run["run_id"] = str(run["run_id"])
    for key in ("created_at", "started_at", "finished_at"):
        run[key] = run[key].isoformat() if run[key] else None
    return run

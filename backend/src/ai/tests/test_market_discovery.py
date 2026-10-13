"""Competitor discovery: industry resolution, each source's parser on the
shapes those APIs really return, de-duplication across sources and
languages, scoring, and the rule that nothing is invented when a source
is unavailable."""
from src.market_scraper.market_discovery import industries, matching, pipeline, scoring
from src.market_scraper.market_discovery.models import Candidate, DiscoveryQuery, ProviderResult
from src.market_scraper.market_discovery.providers import apify_maps, google_places, osm, web_search

AMMAN = (31.9539, 35.9106)


def _query(industry="restaurant", **overrides):
    ind = industries.get(industry)
    values = dict(tenant_id="t", industry_key=ind.key, industry_label=ind.label_en, keywords=list(ind.keywords_en),
                  latitude=AMMAN[0], longitude=AMMAN[1], radius_km=5, city="Amman", country_code="JO",
                  osm_tags=ind.osm_tags, google_types=ind.google_types, own_name="Zaytouna Kitchen")
    values.update(overrides)
    return DiscoveryQuery(**values)


# --- industries ---------------------------------------------------------

def test_industry_resolution_is_generic_across_business_types():
    assert industries.resolve(None, "Family restaurant & grill", [])[0].key == "restaurant"
    assert industries.resolve(None, "صيدلية المدينة", [])[0].key == "pharmacy"
    assert industries.resolve(None, "Boutique hotel", [])[0].key == "hotel"
    assert industries.resolve("cafe", "anything", [])[0].key == "cafe"
    assert industries.resolve(None, None, [])[0].key == "general_retail"


def test_a_business_type_outside_the_table_is_searched_by_its_own_words():
    for description in ("Wedding planner", "مكتب سفريات", "Agence immobilière"):
        industry, how = industries.resolve(None, description, [])
        assert (industry.key, industry.label_en, industry.keywords_en, how) == ("custom", description, (description,), "business_type")
    query = pipeline.build_query("t", {"business_type": "Wedding planner", "city": "Irbid", "country_code": "JO",
                                       "latitude": 32.5556, "longitude": 35.85})
    assert query.industry_key == "custom" and query.osm_tags == () and query.keywords == ["Wedding planner"]
    assert 'nwr["office"]["name"~"Wedding planner|Wedding|planner",i];' in osm.build_query(query)
    # Whole words only: a cardiology clinic is not a car business, a lawn service not a law firm.
    assert industries.resolve(None, "Cardiology centre", [])[0].key != "automotive"
    assert industries.resolve(None, "Lawn care", [])[0].key != "professional_services"
    assert industries.resolve(None, "الصيدلية", [])[0].key == "pharmacy"
    # A listing whose name says it does the same thing ranks, even if its map type is another industry's.
    entity = matching.merge([Candidate(name="Irbid Wedding Planner", source="openstreetmap", source_ref="node/1",
                                       latitude=32.55, longitude=35.85, industry_key="automotive",
                                       raw={"name_match": True})])[0]
    assert scoring.industry_fit(entity, query) == (0.7, "keyword")


def test_the_owners_own_words_are_searched_in_any_language():
    profile = {"industry_key": "hotel", "business_type": "Hôtel boutique", "country_code": "FR", "city": "Lyon",
               "latitude": 45.76, "longitude": 4.84}
    query = pipeline.build_query("t", profile)
    assert query.industry_key == "hotel" and "Hôtel boutique" in query.keywords
    assert pipeline.build_query("t", {**profile, "business_type": "Hotel"}).keywords.count("hotel") == 1  # no duplicate


def test_every_industry_has_search_words_and_a_picker_label():
    for industry in industries.INDUSTRIES.values():
        assert industry.keywords_en and industry.label_ar
        for related in industry.related:
            assert related in industries.INDUSTRIES
    assert {"restaurant", "cafe", "hotel", "supermarket", "pharmacy", "cosmetics", "electronics", "fashion",
            "professional_services"} <= {c["key"] for c in industries.choices()}


def test_osm_and_google_tags_classify_to_the_right_industry():
    assert industries.classify_tags({"amenity": "pharmacy"}) == "pharmacy"
    assert industries.classify_tags({"tourism": "hotel"}) == "hotel"
    assert industries.classify_google_types(["cafe", "food", "point_of_interest"]) == "cafe"
    assert industries.classify_google_types(["point_of_interest"]) is None


# --- providers ----------------------------------------------------------

OVERPASS = {"elements": [
    {"type": "node", "id": 101, "lat": 31.955, "lon": 35.912,
     "tags": {"amenity": "restaurant", "name": "Hashem", "name:ar": "مطعم هاشم", "phone": "+962 6 463 6440",
              "website": "https://hashem.jo", "addr:street": "King Faisal St", "addr:city": "Amman", "cuisine": "arab"}},
    {"type": "way", "id": 202, "center": {"lat": 31.97, "lon": 35.90},
     "tags": {"amenity": "fast_food", "name": "Shawarma Reem"}},
    {"type": "node", "id": 303, "lat": 31.95, "lon": 35.91, "tags": {"amenity": "restaurant"}},  # unnamed: dropped
]}


def test_overpass_query_and_parse():
    query = _query()
    text = osm.build_query(query)
    # A bounding box (index-based) instead of a slow per-element around filter.
    assert "[bbox:31.908984,35.857663,31.998816,35.963537]" in text and "around:" not in text
    assert 'nwr["amenity"="restaurant"]["name"];' in text
    found = osm.parse(OVERPASS, query)
    assert [c.name for c in found] == ["Hashem", "Shawarma Reem"]
    first = found[0]
    assert first.source_ref == "node/101" and first.source_url == "https://www.openstreetmap.org/node/101"
    assert first.name_ar == "مطعم هاشم" and first.industry_key == "restaurant"
    assert first.address == "King Faisal St, Amman"
    assert found[1].latitude == 31.97  # way centre


def test_providers_without_keys_skip_instead_of_inventing(monkeypatch):
    for name in ("GOOGLE_PLACES_API_KEY", "GOOGLE_MAPS_API_KEY", "APIFY_TOKEN", "GOOGLE_CUSTOM_SEARCH_API_KEY",
                 "GOOGLE_CUSTOM_SEARCH_CX", "SEARXNG_INSTANCE_URL", "TAVILY_API_KEY", "BRAVE_SEARCH_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for provider in (google_places, apify_maps, web_search):
        result = provider.search(_query())
        assert result.status == "skipped" and result.reason == "not_configured" and result.candidates == []
    assert osm.search(_query(latitude=None, longitude=None)).reason == "no_location"


def test_unreachable_source_fails_honestly(monkeypatch):
    import httpx

    def boom(*args, **kwargs):
        raise httpx.ConnectError("blocked")

    monkeypatch.setattr(osm, "request_json", boom)
    result = osm.search(_query())
    assert result.status == "failed" and result.candidates == []


def test_a_busy_overpass_server_falls_back_to_the_next_one(monkeypatch):
    import httpx

    monkeypatch.delenv("OVERPASS_API_URL", raising=False)
    monkeypatch.delenv("OVERPASS_API_URLS", raising=False)
    tried = []

    def answer(method, url, **kwargs):
        tried.append(url)
        if len(tried) == 1:
            raise httpx.HTTPStatusError("429", request=httpx.Request("POST", url), response=httpx.Response(429))
        if len(tried) == 2:  # out of time: 200 with a remark and no data
            return {"elements": [], "remark": "runtime error: Query timed out in \"query\" at line 1"}
        return OVERPASS

    monkeypatch.setattr(osm, "request_json", answer)
    result = osm.search(_query())
    assert result.status == "ok" and [c.name for c in result.candidates] == ["Hashem", "Shawarma Reem"]
    assert tried == list(osm.DEFAULT_OVERPASS_URLS) and result.requests == 3
    monkeypatch.setenv("OVERPASS_API_URLS", "https://overpass.example.org/api/interpreter")
    assert osm.overpass_urls() == ["https://overpass.example.org/api/interpreter"]


def test_google_places_parse_and_tiling(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "k")
    calls = []

    def fake(method, url, json_body=None, headers=None, **kwargs):
        calls.append((url, json_body))
        assert headers["X-Goog-Api-Key"] == "k" and "places.id" in headers["X-Goog-FieldMask"]
        return {"places": [
            {"id": "ChIJ1", "displayName": {"text": "Hashem Restaurant"}, "location": {"latitude": 31.9551, "longitude": 35.9121},
             "types": ["restaurant", "food"], "websiteUri": "http://www.hashem.jo/", "rating": 4.5, "userRatingCount": 12000,
             "priceLevel": "PRICE_LEVEL_INEXPENSIVE", "googleMapsUri": "https://maps.google.com/?cid=1", "nationalPhoneNumber": "06 463 6440"},
            {"id": "ChIJ2", "displayName": {"text": "Closed Place"}, "businessStatus": "CLOSED_PERMANENTLY"},
        ]}

    monkeypatch.setattr(google_places, "request_json", fake)
    result = google_places.search(_query(radius_km=8))
    assert result.status == "ok" and len(result.candidates) == 1
    place = result.candidates[0]
    assert place.rating == 4.5 and place.review_count == 12000 and place.price_level == 1 and place.industry_key == "restaurant"
    nearby = [c for c in calls if c[0] == google_places.NEARBY_URL]
    assert len(nearby) == 7  # centre + 6 tiles for a large radius
    assert len(google_places.tiles(AMMAN[0], AMMAN[1], 2)) == 1


def test_apify_parse():
    items = [{"title": "Reem Pharmacy", "placeId": "p1", "url": "https://maps.google.com/?cid=9", "categories": ["Pharmacy"],
              "location": {"lat": 31.96, "lng": 35.91}, "totalScore": 4.1, "reviewsCount": 80, "phone": "079 000 0000"},
             {"title": "Gone", "placeId": "p2", "permanentlyClosed": True}]
    found = apify_maps.parse(items, _query("pharmacy"))
    assert [c.name for c in found] == ["Reem Pharmacy"] and found[0].industry_key == "pharmacy"


def test_web_search_drops_listings_marketplaces_and_listicles():
    items = [
        {"link": "https://www.tripadvisor.com/Restaurants-Amman", "title": "THE 10 BEST Restaurants in Amman"},
        {"link": "https://www.talabat.com/jordan/hashem", "title": "Hashem - Talabat"},
        {"link": "https://www.instagram.com/p/abc/", "title": "post"},
        {"link": "https://www.instagram.com/sufrarestaurant/", "title": "Sufra Restaurant (@sufrarestaurant) • Instagram photos"},
        {"link": "https://www.fakhreldin.com/menu", "title": "Fakhr El-Din | Lebanese Restaurant Amman"},
        {"link": "https://blog.example.com/x", "title": "Top 7 shawarma spots you must try"},
    ]
    found = web_search.parse(items, _query(), "google_search")
    assert [c.name for c in found] == ["Sufra Restaurant", "Fakhr El-Din"]
    assert found[0].website is None and found[0].source_ref == "instagram.com/sufrarestaurant"
    assert found[1].website == "https://fakhreldin.com" and found[1].online_only


# --- matching -----------------------------------------------------------

def _c(name, source, ref, **kw):
    return Candidate(name=name, source=source, source_ref=ref, **kw)


def test_same_business_from_three_sources_merges_into_one():
    found = [
        _c("Hashem", "openstreetmap", "node/1", latitude=31.9550, longitude=35.9120, website="https://hashem.jo", industry_key="restaurant"),
        _c("Hashem Restaurant", "google_places", "ChIJ1", latitude=31.9551, longitude=35.9121, website="http://www.hashem.jo/",
           rating=4.5, review_count=12000, industry_key="restaurant"),
        _c("مطعم هاشم", "google_search", "hashem.jo", website="https://hashem.jo", online_only=True),
        _c("Reem", "openstreetmap", "node/2", latitude=31.97, longitude=35.90, industry_key="restaurant"),
    ]
    entities = matching.merge(found)
    assert len(entities) == 2
    hashem = next(e for e in entities if "hashem.jo" in e.domain_keys)
    assert hashem.sources == {"openstreetmap", "google_places", "google_search"}
    assert len(hashem.branches) == 1  # 15 m apart: one place


def test_arabic_spelling_variants_and_al_prefix_normalise_together():
    assert matching.normalize_name("صيدلية الأمل") == matching.normalize_name("صيدليه الامل")
    assert matching.normalize_name("Al-Amal Pharmacy") == matching.normalize_name("Amal pharmacy")


def test_branches_of_one_brand_are_one_competitor_with_several_places():
    found = [
        _c("Starbucks", "openstreetmap", "node/1", latitude=31.95, longitude=35.91, industry_key="cafe"),
        _c("Starbucks", "openstreetmap", "node/2", latitude=31.99, longitude=35.87, industry_key="cafe"),
    ]
    entities = matching.merge(found)
    assert len(entities) == 1 and len(entities[0].branches) == 2


def test_the_company_itself_is_never_its_own_competitor():
    entity = matching.merge([_c("Zaytouna Kitchen", "openstreetmap", "node/9", latitude=31.95, longitude=35.91)])[0]
    assert matching.is_self(entity, "Zaytouna Kitchen", None)
    assert matching.is_self(matching.merge([_c("Z", "google_search", "z.jo", website="https://z.jo")])[0], "Other", "www.z.jo")


# --- scoring and ranking ------------------------------------------------

def test_ranking_prefers_same_industry_nearby_and_drops_other_industries():
    query = _query()
    results = [ProviderResult("openstreetmap", "ok", [
        _c("Near Grill", "openstreetmap", "node/1", latitude=31.9545, longitude=35.9110, industry_key="restaurant"),
        _c("Far Grill", "openstreetmap", "node/2", latitude=31.99, longitude=35.95, industry_key="restaurant"),
        _c("Corner Cafe", "openstreetmap", "node/3", latitude=31.9541, longitude=35.9108, industry_key="cafe"),
        _c("Tyre Shop", "openstreetmap", "node/4", latitude=31.9541, longitude=35.9108, industry_key="automotive"),
        _c("Zaytouna Kitchen", "openstreetmap", "node/5", latitude=31.954, longitude=35.911, industry_key="restaurant"),
    ])]
    ranked = pipeline.rank(query, results)
    names = [r[0].name for r in ranked]
    assert names[0] == "Near Grill"
    assert "Tyre Shop" not in names and "Zaytouna Kitchen" not in names
    assert names.index("Near Grill") < names.index("Far Grill")
    near = ranked[0]
    assert {"code": "same_industry"} in near[4] and any(r["code"] == "distance" for r in near[4])


def test_confidence_grows_with_independent_sources():
    one = matching.merge([_c("A", "openstreetmap", "n/1", latitude=1, longitude=1)])[0]
    two = matching.merge([_c("A", "openstreetmap", "n/1", latitude=1, longitude=1),
                          _c("A", "google_places", "g1", latitude=1, longitude=1, website="https://a.jo", review_count=50)])[0]
    assert scoring.confidence(two) > scoring.confidence(one)


def test_query_uses_arabic_words_in_arabic_markets_and_product_categories():
    profile = {"name": "X", "business_type": "pharmacy", "country_code": "JO", "city": "Amman", "latitude": 1.0,
               "longitude": 2.0, "top_categories": ["Baby care"], "product_names": []}
    query = pipeline.build_query("t", profile)
    assert query.industry_key == "pharmacy" and query.keywords[0] == "صيدلية" and "Baby care" in query.keywords
    assert query.radius_km == industries.get("pharmacy").default_radius_km
    fr = pipeline.build_query("t", {**profile, "country_code": "FR"})
    assert "صيدلية" not in fr.keywords


def test_a_failed_run_blames_unreachable_sources_before_the_location():
    failed = [ProviderResult("openstreetmap", "skipped", reason="no_location"), ProviderResult("place_search", "failed", reason="unreachable")]
    assert pipeline._failure_reason(_query(latitude=None, longitude=None), failed) == "unreachable"
    skipped = [ProviderResult("openstreetmap", "skipped", reason="no_location"), ProviderResult("place_search", "skipped", reason="no_location")]
    assert pipeline._failure_reason(_query(latitude=None, longitude=None), skipped) == "location_not_found"
    assert pipeline._failure_reason(_query(latitude=None, longitude=None, city=None), skipped) == "no_location"
    assert pipeline._failure_reason(_query(), [ProviderResult("web_search", "skipped", reason="not_configured")]) == "no_sources"


def test_amman_and_other_cities_get_a_location_without_any_service():
    from src.market_scraper.market_discovery import cities, geocode

    amman = (31.9539, 35.9106)
    for text in ("Amman", "amman", "Amman, Jordan", "Amman - Khalda", "عمّان", "عمان", "  AMMAN  "):
        assert cities.lookup(text, "JO") == amman, text
    assert cities.lookup("إربد", "JO") == (32.5556, 35.85) and cities.lookup("Jeddah", "SA") == (21.4858, 39.1925)
    assert cities.lookup("عمان", "OM") is None  # Arabic "Oman" (the country) is not Amman
    assert cities.lookup("Atlantis", "JO") is None and cities.lookup(None) is None

    def offline(*args, **kwargs):
        raise AssertionError("no service should be asked for Amman")

    import pytest
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(geocode, "request_json", offline)
        assert geocode.geocode_city("Amman", "JO") == amman


def test_an_unlisted_city_falls_through_geocoders_one_failing_never_stopping_the_next(monkeypatch):
    import httpx
    from src.market_scraper.market_discovery import geocode

    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    asked = []

    def answer(method, url, params=None, **kwargs):
        asked.append(url)
        if "nominatim" in url:
            raise httpx.HTTPStatusError("403", request=httpx.Request("GET", url), response=httpx.Response(403))
        return {"features": [{"geometry": {"coordinates": [35.2, 31.3]}, "properties": {"countrycode": "JO"}}]}

    monkeypatch.setattr(geocode, "request_json", answer)
    assert geocode.geocode_city("Some Village", "JO") == (31.3, 35.2)
    assert [("nominatim" in u, "photon" in u) for u in asked] == [(True, False), (False, True)]


def test_industries_without_map_types_are_searched_by_business_name():
    query = _query("online_retail", keywords=["متجر إلكتروني", "online store", "Sweets", "حلويات"], osm_tags=())
    text = osm.build_query(query)
    assert 'nwr["shop"]["name"~"متجر إلكتروني|Sweets|حلويات",i];' in text
    payload = {"elements": [{"type": "node", "id": 7, "lat": 31.95, "lon": 35.91,
                             "tags": {"shop": "yes", "name": "حلويات نفيسة", "name:en": "Nafiseh Sweets"}}]}
    found = osm.parse(payload, query)
    assert found[0].raw["name_match"] is True and found[0].industry_key is None
    entity = matching.merge(found)[0]
    assert scoring.industry_fit(entity, query) == (0.7, "keyword")
    assert osm.search(_query("online_retail", keywords=["store"], osm_tags=())).reason == "industry_not_mapped"


def test_overpass_drops_the_search_box_corners():
    query = _query()
    corner = {"elements": [{"type": "node", "id": 9, "lat": 31.9539 + 0.044, "lon": 35.9106 + 0.052,
                            "tags": {"amenity": "restaurant", "name": "Far Corner Grill"}}]}
    assert osm.parse(corner, query) == []  # ~6.9 km away with a 5 km radius


def test_overpass_retries_lighter_and_never_caches_a_timeout(monkeypatch):
    asked = []

    def fake(method, url, data=None, timeout=None, cache_if=None, **_):
        asked.append(("[\"name\"~" in data["data"], url))
        timed_out = {"elements": [], "remark": "runtime error: Query timed out in \"query\" at line 1 after 26 seconds."}
        assert cache_if(timed_out) is False and cache_if(OVERPASS) is True
        return timed_out if "[\"name\"~" in data["data"] else OVERPASS
    monkeypatch.setattr(osm, "request_json", fake)
    monkeypatch.setattr(osm, "overpass_urls", lambda: ["https://a.example", "https://b.example"])
    result = osm.search(_query(keywords=["restaurant", "مطعم"]))
    assert result.status == "ok" and [c.name for c in result.candidates] == ["Hashem", "Shawarma Reem"]
    assert asked == [(True, "https://a.example"), (True, "https://b.example"), (False, "https://a.example")]
    assert result.requests == 3


def test_a_listing_named_only_after_its_trade_is_not_a_competitor():
    query = _query("bakery", keywords=["bakery", "مخبز", "حلويات"])
    assert pipeline._generic_name("Bakery", query) and pipeline._generic_name(" حلويات ", query)
    assert pipeline._generic_name("خاص", query)
    assert not pipeline._generic_name("Abu Khamees Bakery", query) and not pipeline._generic_name("حلويات نفيسة", query)


def test_a_website_given_without_https_is_a_usable_address():
    from src.market_scraper.market_discovery.models import web_address
    assert web_address("tottis.jo") == "https://tottis.jo"
    assert web_address("www.aquel-restaurant.com/menu") == "https://www.aquel-restaurant.com/menu"
    assert web_address("http://x.com; https://y.com") == "http://x.com"
    assert web_address("not a site") is None and web_address(None) is None
    assert Candidate(name="Luna Rossa", source="openstreetmap", source_ref="node/1", website="tottis.jo").website == "https://tottis.jo"

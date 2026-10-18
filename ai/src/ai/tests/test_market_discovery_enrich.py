"""Website enrichment: what a competitor's own homepage adds, read only
where robots.txt allows and only from public addresses, and the rule that
an unreadable site adds nothing."""
import httpx
import pytest

from src.market_scraper.market_discovery import enrich, industries, pipeline, scoring
from src.market_scraper.market_discovery.models import Candidate, DiscoveryQuery, ProviderResult
from src.market_scraper.network_security import UnsafeTargetError

AMMAN = (31.9539, 35.9106)

HOMEPAGE = """<!doctype html><html><head>
<title>Olive &amp; Thyme | Lebanese kitchen in Amman</title>
<meta name="description" content="Family Lebanese restaurant in Jabal Amman since 2009.">
<script type="application/ld+json">
{"@context": "https://schema.org", "@graph": [
  {"@type": "WebSite", "name": "Olive & Thyme"},
  {"@type": ["Restaurant", "LocalBusiness"], "name": "Olive & Thyme", "telephone": "+962 6 555 0101",
   "address": {"@type": "PostalAddress", "streetAddress": "Rainbow St 12", "addressLocality": "Amman", "addressCountry": "JO"},
   "sameAs": ["https://www.instagram.com/oliveandthyme.jo"]}
]}
</script></head><body>
<a href="https://facebook.com/oliveandthyme">Facebook</a>
<a href="https://www.facebook.com/sharer/sharer.php?u=x">Share</a>
<a href="/menu">Menu</a>
</body></html>"""


def _query(industry="restaurant"):
    ind = industries.get(industry)
    return DiscoveryQuery(tenant_id="t", industry_key=ind.key, industry_label=ind.label_en, keywords=list(ind.keywords_en),
                          latitude=AMMAN[0], longitude=AMMAN[1], radius_km=5, city="Amman", country_code="JO",
                          osm_tags=ind.osm_tags, google_types=ind.google_types)


def test_homepage_parsing_reads_schema_meta_and_social_profiles():
    page = enrich.parse_homepage(HOMEPAGE, "https://oliveandthyme.jo/")
    assert page["schema_types"] == ["Restaurant", "LocalBusiness"]
    assert page["name"] == "Olive & Thyme"
    assert page["phone"] == "+962 6 555 0101"
    assert page["address"] == "Rainbow St 12, Amman, JO"
    assert page["description"].startswith("Family Lebanese restaurant")
    assert page["title"].startswith("Olive & Thyme")
    # Profiles are kept; share buttons and the site's own links are not.
    assert page["social"] == ["https://www.instagram.com/oliveandthyme.jo", "https://facebook.com/oliveandthyme"]


def test_broken_json_ld_is_ignored_not_fatal():
    page = enrich.parse_homepage('<script type="application/ld+json">{not json</script><meta name="description" content="x">', "https://a.example/")
    assert page["schema_types"] == [] and page["description"] == "x"


def test_schema_types_map_to_industries():
    assert enrich.schema_industry(["Restaurant"]) == "restaurant"
    assert enrich.schema_industry(["CafeOrCoffeeShop"]) == "cafe"
    assert enrich.schema_industry(["Pharmacy"]) == "pharmacy"
    assert enrich.schema_industry(["Hotel"]) == "hotel"
    assert enrich.schema_industry(["Thing"]) is None


def _ranked(candidates, query):
    return pipeline.rank(query, [ProviderResult("openstreetmap", "ok", candidates)])


def test_enrichment_adds_a_website_source_and_raises_confidence():
    query = _query()
    candidate = Candidate(name="Olive & Thyme", source="openstreetmap", source_ref="node/1", website="https://oliveandthyme.jo",
                          latitude=AMMAN[0] + 0.005, longitude=AMMAN[1], industry_key=None)
    ranked = _ranked([candidate], query)
    before = ranked[0][2]
    seen = []

    def fake_fetch(url):
        seen.append(url)
        page = enrich.parse_homepage(HOMEPAGE, url)
        page["final_url"] = url
        return page

    counts = enrich.enrich(ranked, fetch=fake_fetch, limit=15)
    assert counts == {"checked": 1, "read": 1, "blocked": 0}
    assert seen == ["https://oliveandthyme.jo"]
    entity = ranked[0][0]
    assert "website" in entity.sources
    website = next(c for c in entity.candidates if c.source == "website")
    assert website.industry_key == "restaurant" and website.raw["social"]
    rescored = pipeline.rescore(query, ranked)
    assert rescored[0][2] > before
    # The website confirms the industry, so relevance can only go up.
    assert rescored[0][1] >= ranked[0][1]


def test_platform_links_are_not_treated_as_the_business_website():
    query = _query()
    candidate = Candidate(name="Cafe X", source="openstreetmap", source_ref="node/2", website="https://instagram.com/cafex",
                          latitude=AMMAN[0], longitude=AMMAN[1], industry_key="restaurant")
    calls = []
    counts = enrich.enrich(_ranked([candidate], query), fetch=lambda url: calls.append(url), limit=15)
    assert counts["checked"] == 0 and calls == []


def test_unreadable_or_robots_blocked_sites_add_nothing():
    query = _query()
    a = Candidate(name="A Grill", source="openstreetmap", source_ref="node/3", website="https://a-grill.example",
                  latitude=AMMAN[0], longitude=AMMAN[1], industry_key="restaurant")
    b = Candidate(name="B Diner", source="openstreetmap", source_ref="node/4", website="https://b-diner.example",
                  latitude=AMMAN[0], longitude=AMMAN[1] + 0.01, industry_key="restaurant")
    ranked = _ranked([a, b], query)
    counts = enrich.enrich(ranked, fetch=lambda url: {"blocked": "robots"} if "a-grill" in url else None, limit=15)
    assert counts == {"checked": 2, "read": 0, "blocked": 1}
    assert all("website" not in entity.sources for entity, *_ in ranked)


def test_confidence_counts_the_own_website_less_than_an_independent_source():
    query = _query()
    base = Candidate(name="Z", source="openstreetmap", source_ref="n", latitude=AMMAN[0], longitude=AMMAN[1], industry_key="restaurant")
    with_site = [base, Candidate(name="Z", source="website", source_ref="z.example", industry_key="restaurant")]
    with_listing = [base, Candidate(name="Z", source="google_places", source_ref="g", latitude=AMMAN[0], longitude=AMMAN[1])]
    site_conf = scoring.confidence(_ranked(with_site, query)[0][0])
    listing_conf = scoring.confidence(_ranked(with_listing, query)[0][0])
    assert listing_conf > site_conf > scoring.confidence(_ranked([base], query)[0][0])


def test_private_addresses_are_refused(monkeypatch):
    def private_resolver(url):
        raise UnsafeTargetError("private")
    monkeypatch.setattr(enrich, "resolve_public_addresses", private_resolver)
    # Refused before any request; it counts as unreadable, not as robots-blocked.
    assert enrich.fetch_site("http://10.0.0.5/") is None


def test_robots_disallow_stops_the_fetch(monkeypatch):
    monkeypatch.setattr(enrich, "resolve_public_addresses", lambda url: {"93.184.216.34"})
    fetched = []

    def handler(request):
        fetched.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
        return httpx.Response(200, text=HOMEPAGE, headers={"content-type": "text/html"})

    real_client = httpx.Client
    monkeypatch.setattr(enrich.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    assert enrich.fetch_site("https://shop.example/") == {"blocked": "robots"}
    assert fetched == ["/robots.txt"]


def test_allowed_site_is_read(monkeypatch):
    monkeypatch.setattr(enrich, "resolve_public_addresses", lambda url: {"93.184.216.34"})

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=HOMEPAGE, headers={"content-type": "text/html; charset=utf-8"})

    real_client = httpx.Client
    monkeypatch.setattr(enrich.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    page = enrich.fetch_site("https://oliveandthyme.jo/")
    assert page["schema_types"][0] == "Restaurant" and page["final_url"] == "https://oliveandthyme.jo/"


@pytest.mark.parametrize("path", ["/robots.txt"])
def test_robots_server_error_means_not_allowed(monkeypatch, path):
    monkeypatch.setattr(enrich, "resolve_public_addresses", lambda url: {"93.184.216.34"})
    real_client = httpx.Client
    handler = lambda request: httpx.Response(503) if request.url.path == path else httpx.Response(200, text=HOMEPAGE)  # noqa: E731
    monkeypatch.setattr(enrich.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    # A 5xx robots.txt can't be read: treat the site as not allowed.
    assert enrich.fetch_site("https://shop.example/") == {"blocked": "robots"}


def test_profile_links_are_deduplicated_across_sources_and_only_http():
    from src.ai.market_inputs.discovered_competitors import _profiles

    payloads = [
        {"social": ["https://www.instagram.com/olive.jo/", "javascript:alert(1)"]},
        {"social": True},  # web search marks a social hit with a flag, not links
        None,
        {"social": ["https://instagram.com/olive.jo", "https://facebook.com/olive"]},
    ]
    assert _profiles(payloads) == ["https://www.instagram.com/olive.jo/", "https://facebook.com/olive"]

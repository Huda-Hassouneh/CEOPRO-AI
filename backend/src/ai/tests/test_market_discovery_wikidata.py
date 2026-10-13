"""Wikidata as a discovery source: the two API calls it makes, keeping
only organisations, the facts it reads (website, social accounts,
founding year) and honest skip/failure."""
import httpx

from src.ai.market_inputs import public_sources
from src.market_scraper.market_discovery.models import DiscoveryQuery
from src.market_scraper.market_discovery.providers import wikidata


def _claim(value):
    if isinstance(value, str) and value.startswith("Q"):
        datavalue = {"value": {"entity-type": "item", "numeric-id": int(value[1:]), "id": value}, "type": "wikibase-entityid"}
    elif isinstance(value, str) and value.startswith("+"):
        datavalue = {"value": {"time": value, "precision": 9}, "type": "time"}
    else:
        datavalue = {"value": value, "type": "string"}
    return {"mainsnak": {"snaktype": "value", "datavalue": datavalue}, "type": "statement", "rank": "normal"}


def _entity(qid, en=None, ar=None, description=None, **claims):
    return {"type": "item", "id": qid,
            "labels": {k: {"language": k, "value": v} for k, v in (("en", en), ("ar", ar)) if v},
            "descriptions": {"en": {"language": "en", "value": description}} if description else {},
            "claims": {prop: [_claim(v) for v in values] for prop, values in claims.items()}}


SEARCH = {"batchcomplete": "", "query": {"searchinfo": {"totalhits": 3}, "search": [
    {"ns": 0, "title": "Q111", "pageid": 1}, {"ns": 0, "title": "Q222", "pageid": 2}, {"ns": 0, "title": "Q333", "pageid": 3}]}}
ENTITIES = {"entities": {
    "Q111": _entity("Q111", en="Habibah Sweets", ar="حلويات حبيبة", description="Jordanian sweets maker",
                    P31=["Q4830453"], P17=["Q810"], P856=["https://habibah.jo/"], P2003=["habibahsweets"],
                    P2013=["HabibahSweets"], P571=["+1951-00-00T00:00:00Z"]),
    "Q222": _entity("Q222", en="Ahmad Habibah", P31=["Q5"], P27=["Q810"]),          # a person: dropped
    "Q333": _entity("Q333", en="Amman", P31=["Q515"], P17=["Q810"], P856=["https://amman.jo"]),  # a city: dropped
}}


def _query(**overrides):
    values = dict(tenant_id="t", industry_key="bakery", industry_label="Bakery & sweets", keywords=["sweets", "bakery"],
                  city="Amman", country_code="JO")
    values.update(overrides)
    return DiscoveryQuery(**values)


def test_organisations_with_their_recorded_facts_and_wikidata_page():
    found = wikidata.parse_entities(ENTITIES, _query())
    assert [c.name for c in found] == ["Habibah Sweets"]
    habibah = found[0]
    assert habibah.source == "wikidata" and habibah.source_url == "https://www.wikidata.org/wiki/Q111"
    assert habibah.name_ar == "حلويات حبيبة" and habibah.website == "https://habibah.jo/"
    assert habibah.raw["social"] == ["https://www.instagram.com/habibahsweets", "https://www.facebook.com/HabibahSweets"]
    assert habibah.raw["founded"] == "1951" and habibah.raw["snippet"] == "Jordanian sweets maker"


def test_search_is_limited_to_the_country_and_fetches_entities_once(monkeypatch):
    calls = []

    def fake(method, url, params=None, **kwargs):
        calls.append(params)
        return SEARCH if params["action"] == "query" else ENTITIES

    monkeypatch.setattr(wikidata, "request_json", fake)
    result = wikidata.search(_query())
    assert result.status == "ok" and [c.name for c in result.candidates] == ["Habibah Sweets"]
    assert [c["srsearch"] for c in calls if c["action"] == "query"] == ["sweets haswbstatement:P17=Q810", "bakery haswbstatement:P17=Q810"]
    assert [c["ids"] for c in calls if c["action"] == "wbgetentities"] == ["Q111|Q222|Q333"]  # de-duplicated
    assert result.requests == 3


def test_any_country_is_found_by_its_iso_code_and_unknown_codes_skip(monkeypatch):
    asked = []

    def fake(method, url, params=None, **kwargs):
        asked.append(params["srsearch"] if params["action"] == "query" else "entities")
        if params["srsearch"] == "haswbstatement:P297=NL":
            return {"query": {"search": [{"title": "Q55"}]}}
        return {"query": {"search": []}}

    monkeypatch.setattr(wikidata, "request_json", fake)
    assert wikidata.country_item("JO") == "Q810" and asked == []  # known without a request
    assert wikidata.country_item("nl") == "Q55"
    result = wikidata.search(_query(country_code="NL"))
    assert result.status == "ok" and "sweets haswbstatement:P17=Q55" in asked
    assert wikidata.search(_query(country_code="ZZ")).reason == "country_not_covered"


def test_unreachable_fails(monkeypatch):

    def down(*args, **kwargs):
        raise httpx.ConnectError("blocked")

    monkeypatch.setattr(wikidata, "request_json", down)
    result = wikidata.search(_query())
    assert result.status == "failed" and result.candidates == []


def test_customers_see_a_company_database_with_a_link_to_check():
    merged = public_sources.merge_sources([
        {"source": "wikidata", "url": "https://www.wikidata.org/wiki/Q111", "last_seen_at": "2026-10-09"},
        {"source": "openstreetmap", "url": "https://www.openstreetmap.org/node/1", "last_seen_at": "2026-10-08"},
    ])
    assert [(m["source"], m["label"], m["url"]) for m in merged] == [
        ("company_database", "Public company database", "https://www.wikidata.org/wiki/Q111"),
        ("map_listing", "Public business listing", "https://www.openstreetmap.org/node/1"),
    ]

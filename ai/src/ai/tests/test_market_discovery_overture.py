"""Overture Maps places as a discovery source: which places count as
competitors, their names and links, and the parts of the dataset read.
Rows below have the shape of the real dataset's rows."""
from src.market_scraper.market_discovery import industries, pipeline
from src.market_scraper.market_discovery.models import DiscoveryQuery
from src.market_scraper.market_discovery.providers import osm, overture


def _query(industry="pharmacy", **overrides):
    ind = industries.get(industry)
    values = dict(tenant_id="t", industry_key=ind.key, industry_label=ind.label_en, keywords=["صيدلية", "pharmacy"],
                  latitude=24.7136, longitude=46.6753, radius_km=10, city="Riyadh", country_code="SA",
                  osm_tags=ind.osm_tags, google_types=ind.google_types)
    values.update(overrides)
    return DiscoveryQuery(**values)


def _row(name, category, datasets, socials=None, websites=None, record="123"):
    return {"id": "08f-" + name, "names": {"primary": name, "common": None}, "basic_category": category,
            "taxonomy": {"primary": category, "hierarchy": [category], "alternates": None},
            "websites": websites, "socials": socials, "phones": ["+966 11 000 0000"],
            "addresses": [{"freeform": "King Fahd Rd", "locality": "Riyadh", "country": "SA"}],
            "sources": [{"dataset": d, "record_id": record} for d in datasets] + [{"dataset": "Overture", "record_id": None}],
            "confidence": 0.8, "operating_status": "open",
            "bbox": {"xmin": 46.68, "xmax": 46.68, "ymin": 24.72, "ymax": 24.72}}


def test_a_category_counts_only_from_a_reliable_contributor_or_with_the_name_agreeing():
    assert overture._category_trusted(_row("Nahdi", "pharmacy", ["meta"]))
    assert not overture._category_trusted(_row("كنتاكي", "pharmacy", ["Microsoft"]))  # KFC filed as a pharmacy
    assert overture._category_trusted(_row("Boots", "pharmacy", ["Microsoft", "Foursquare"]))


def test_match_words_come_from_the_query_not_from_any_fixed_list():
    assert "pharmacy" in overture.match_words(_query()) and "chemist" in overture.match_phrases(_query())
    restaurant = _query("restaurant", keywords=["restaurant"])
    assert overture.category_matches(_row("Reem", "fast_food_restaurant", ["meta"]), overture.match_words(restaurant), overture.match_phrases(restaurant))
    assert not overture.category_matches(_row("Club", "tennis_court", ["meta"]), overture.match_words(restaurant), overture.match_phrases(restaurant))
    custom = _query("restaurant", industry_key="custom", industry_label="Software company", keywords=["Software company"],
                    osm_tags=(), google_types=())
    assert overture.match_words(custom) == {"software"}  # "company" says nothing


def test_a_place_becomes_a_candidate_with_its_names_and_a_link_to_where_it_came_from():
    q = _query()
    meta = overture.to_candidate(_row("صيدلية ليمون", "pharmacy", ["meta"], socials=["https://www.facebook.com/1234"]), q, True, True)
    assert (meta.name, meta.name_ar, meta.source_url, meta.industry_key) == ("صيدلية ليمون", "صيدلية ليمون", "https://www.facebook.com/1234", "pharmacy")
    venue = overture.to_candidate(_row("Boots", "pharmacy", ["Foursquare"], record="4be3", websites=["boots.com.sa"]), q, True, False)
    assert venue.source_url == "https://foursquare.com/v/4be3" and venue.website == "https://boots.com.sa"
    assert overture.to_candidate(_row("Whites", "pharmacy", ["AllThePlaces"], websites=["https://www.whites.net/ar/"]), q, True, False).source_url == "https://www.whites.net/ar/"


def test_only_the_parts_of_the_dataset_around_the_company_are_read():
    class Stat:
        def __init__(self, low, high):
            self.min, self.max = low, high

    class Column:
        def __init__(self, path, stat):
            self.path_in_schema, self.path, self.statistics = path, path, stat

    class RowGroup:
        def __init__(self, x, y):
            self.cols = [Column("bbox.xmin", Stat(x, x + 1)), Column("bbox.xmax", Stat(x, x + 1)),
                         Column("bbox.ymin", Stat(y, y + 1)), Column("bbox.ymax", Stat(y, y + 1))]

        def column(self, i):
            return self.cols[i]

    class Meta:
        def __init__(self, groups):
            self.groups, self.num_row_groups, self.num_columns = groups, len(groups), 4
            self.schema = self

        def column(self, i):
            return self.groups[0].cols[i]

        def row_group(self, i):
            return self.groups[i]

    index = {"files": [("a.parquet", 1, Meta([RowGroup(46.2, 24.3), RowGroup(35.5, 31.5), RowGroup(-74, 40)]))]}
    assert [g[3] for g in overture._row_groups(index, overture._box(_query()))] == [0]


def test_a_business_type_described_in_arabic_matches_names_by_word_stem():
    import re
    pattern = re.compile(osm._name_pattern(["مكتب عقاري"], by_word=True))
    assert pattern.search("مكتب الدوحة للعقارات") and pattern.search("شركة العقارية المتحدة")
    assert not pattern.search("مكتب محاماة")  # "office" alone is not the trade


def test_arabic_only_descriptions_get_english_category_words_once():
    asked = []
    query = pipeline.build_query("t", {"business_type": "مكتب عقاري", "city": "Doha", "country_code": "QA",
                                       "latitude": 25.2854, "longitude": 51.531})
    pipeline._CATEGORY_WORDS_CACHE.clear()

    def ask(messages, **kwargs):
        asked.append(messages[-1]["content"])
        return '["real estate agent", "property management"]'

    enriched = pipeline.with_category_words(query, ask=ask)
    assert set(enriched.category_words) == {"estate", "property"}  # not "real", "agent", "management"
    assert "real estate agent" in enriched.keywords and "مكتب عقاري" in enriched.keywords
    pipeline.with_category_words(query, ask=ask)
    assert len(asked) == 1  # cached
    english = pipeline.build_query("t", {"business_type": "Software company", "latitude": 1, "longitude": 1})
    assert pipeline.with_category_words(english, ask=ask) is english  # English already: nothing asked

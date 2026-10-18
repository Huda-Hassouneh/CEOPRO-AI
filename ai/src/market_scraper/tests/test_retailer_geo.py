from src.market_scraper.direct_search import retailer_domains_for
from src.market_scraper.retailer_geo import known_origin_country


def test_us_only_retailers_are_not_offered_to_a_jordan_tenant():
    assert retailer_domains_for("electronics_hobbyist", "JO", []) == []


def test_us_tenant_gets_us_retailers_but_not_a_chinese_one():
    domains = retailer_domains_for("electronics_hobbyist", "US", [])
    assert "www.sparkfun.com" in domains and "www.dfrobot.com" not in domains


def test_operating_countries_count_as_markets():
    assert "www.dfrobot.com" in retailer_domains_for("electronics_hobbyist", "JO", ["CN"])


def test_unknown_tenant_country_keeps_everything():
    assert len(retailer_domains_for("electronics_hobbyist", None, [])) == 4


def test_unknown_vertical_has_no_seeded_domains():
    assert retailer_domains_for("food_beverage", "JO", []) == []


def test_operator_verified_international_domain_is_kept_and_not_out_of_region(monkeypatch):
    monkeypatch.setenv("RETAILER_INTERNATIONAL_DOMAINS", "www.sparkfun.com, www.dfrobot.com")
    assert known_origin_country("www.sparkfun.com") is None
    assert set(retailer_domains_for("electronics_hobbyist", "JO", [])) == {"www.sparkfun.com", "www.dfrobot.com"}


def test_unlisted_domain_has_unknown_origin():
    assert known_origin_country("some-new-shop.example") is None
    assert known_origin_country("www.sparkfun.com") == "US"


def test_maps_url_from_coordinates_or_none():
    from src.market_scraper.geo import maps_url
    assert maps_url(31.95, 35.91) == "https://www.google.com/maps/search/?api=1&query=31.95,35.91"
    assert maps_url(None, 35.91) is None and maps_url(31.95, None) is None

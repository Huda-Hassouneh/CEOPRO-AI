"""Competitor products and prices: reading them from sites (shop platforms'
catalogues, sitemaps, MENA price formats, failure reasons), matching them to
the company's own products, and how each business is classified (direct /
indirect / related / unverified). Pages and payloads have the shapes real
sites publish."""
import json

import httpx

from src.market_scraper.market_discovery import industries, intel, matching, offerings, pipeline, relevance
from src.market_scraper.market_discovery.models import Candidate, DiscoveryQuery
from src.market_scraper.network_security import UnsafeTargetError


def _query(industry="restaurant", **overrides):
    ind = industries.get(industry)
    values = dict(tenant_id="t", industry_key=ind.key, industry_label=ind.label_en, keywords=list(ind.keywords_en),
                  latitude=31.9539, longitude=35.9106, radius_km=10, city="Amman", country_code="JO",
                  osm_tags=ind.osm_tags, google_types=ind.google_types)
    values.update(overrides)
    return DiscoveryQuery(**values)


# --- reading sites -----------------------------------------------------------

def test_arabic_digits_regional_currencies_units_and_ranges():
    assert intel.text_prices(["منسف لحم ٨٫٥٠ د.أ"], "JO") == [{"name": "منسف لحم", "price": 8.5, "currency": "JOD"}]
    assert intel.text_prices(["كبسة دجاج 25 ريال"], "QA")[0]["currency"] == "QAR"  # ريال by the site's country
    assert intel.text_prices(["Mixed grill 7.5 دينار"], "KW")[0]["currency"] == "KWD"
    assert intel.text_prices(["Tagine 85 DH"], "MA")[0]["currency"] == "MAD"
    assert intel.text_prices(["Kunafa 3,500 JD"], "JO")[0]["price"] == 3.5          # three-decimal dinar
    assert intel.text_prices(["Suite 1,250 SAR / night"], "SA")[0]["price"] == 1250.0
    assert intel.text_prices(["Room 45 - 60 JD"], "JO")[0] == {"name": "Room", "price": 45.0, "currency": "JOD", "price_max": 60.0}
    assert intel.text_prices(["Pro 5 package", "Call +962790000000", "2026"], "OM") == []


def test_amounts_without_a_currency_count_only_as_a_menu_list():
    lines = ["Hummus", "Falafel 1.5", "Mutabbal 2", "Fattoush 2.25"]
    assert intel.text_prices(lines, "JO") == []
    listed = intel.text_prices(lines, "JO", menu_page=True)
    assert [(i["name"], i["price"], i["currency"], i["currency_inferred"]) for i in listed] == [
        ("Falafel", 1.5, "JOD", True), ("Mutabbal", 2.0, "JOD", True), ("Fattoush", 2.25, "JOD", True)]


SHOP_HOME = '<html><head><script src="https://cdn.shopify.com/s/x.js"></script><script>Shopify.currency = {"active":"SAR","rate":"1.0"};</script></head><body>' + "x" * 400 + "</body></html>"
SHOPIFY = {"products": [
    {"title": "Vitamin C 1000mg", "handle": "vitamin-c", "product_type": "Supplements",
     "variants": [{"price": "45.00", "compare_at_price": "60.00"}, {"price": "80.00"}]},
    {"title": "Gift card", "handle": "gift", "variants": []}]}


def test_a_shopify_stores_own_catalogue_is_read_with_discounts():
    pages = {"https://pharma.example.sa": SHOP_HOME, "https://pharma.example.sa/products.json?limit=250": json.dumps(SHOPIFY)}
    result = intel.collect("https://pharma.example.sa", fetch=lambda url: pages.get(url.rstrip("/")))
    assert result["platform"] == "shopify" and result["status"] == intel.STATUS_PRICES
    item = next(f for f in result["facts"] if f["kind"] == "product")
    assert (item["name"], item["price"], item["price_max"], item["original_price"], item["currency"]) == (
        "Vitamin C 1000mg", 45.0, 80.0, 60.0, "SAR")
    assert item["source_url"] == "https://pharma.example.sa/products/vitamin-c" and item["confidence"] == intel.CONFIDENCE_CATALOG


def test_a_woocommerce_store_api_list_is_read_in_minor_units():
    items = intel.woocommerce_products([{"name": "Baklava 1kg", "permalink": "https://s.jo/p/baklava",
                                         "prices": {"price": "12500", "regular_price": "15000", "currency_code": "JOD",
                                                    "currency_minor_unit": 3}, "categories": [{"name": "Sweets"}]}], "https://s.jo")
    assert items == [{"name": "Baklava 1kg", "type": "product", "price": 12.5, "currency": "JOD",
                      "source_url": "https://s.jo/p/baklava", "original_price": 15.0, "section": "Sweets"}]


def test_menu_pages_are_found_through_the_sitemap_robots_txt_names():
    home = "<html><body>" + "Welcome " * 60 + "<a href='/about'>About</a></body></html>"
    robots = "User-agent: *\nAllow: /\nSitemap: https://r.jo/sitemap.xml"
    sitemap = "<urlset><url><loc>https://r.jo/ar/المنيو</loc></url><url><loc>https://r.jo/contact</loc></url></urlset>"
    menu = "<html><head><title>المنيو</title></head><body><ul><li>منسف 6.50 د.أ</li><li>مقلوبة 5 د.أ</li></ul>" + "x " * 200 + "</body></html>"
    pages = {"https://r.jo": home, "https://r.jo/robots.txt": robots, "https://r.jo/sitemap.xml": sitemap,
             "https://r.jo/ar/المنيو": menu}
    result = intel.collect("https://r.jo", fetch=lambda url: pages.get(url.rstrip("/")))
    assert result["pages_read"] == ["https://r.jo", "https://r.jo/ar/المنيو"]
    assert {(f["name"], f["price"]) for f in result["facts"] if f["kind"] == "product"} == {("منسف", 6.5), ("مقلوبة", 5.0)}


def test_every_failure_has_its_own_reason():
    def dns_fails(url):
        raise UnsafeTargetError("target DNS resolution failed: r.jo")

    def private(url):
        raise UnsafeTargetError("target resolves to prohibited address: 10.0.0.1")

    def down(url):
        raise httpx.ConnectTimeout("timeout")

    assert intel.collect("r.jo", fetch=dns_fails)["status"] == intel.STATUS_UNREACHABLE
    assert intel.collect("r.jo", fetch=private)["status"] == intel.STATUS_NOT_PUBLIC
    assert intel.collect("r.jo", fetch=down)["status"] == intel.STATUS_UNREACHABLE
    assert intel.collect("r.jo", fetch=lambda url: None)["status"] == intel.STATUS_ROBOTS
    about_only = "<html><body>" + "We are a family business. " * 30 + "</body></html>"
    assert intel.collect("r.jo", fetch=lambda url: about_only if url.rstrip("/") == "https://r.jo" else None)["status"] == intel.STATUS_NO_PAGE
    menu_no_prices = "<html><body><a href='/menu'>Menu</a>" + "Fresh food daily. " * 30 + "</body></html>"
    pages = {"https://r.jo": menu_no_prices, "https://r.jo/menu": "<html><body>" + "Mansaf, maqluba, musakhan. " * 20 + "</body></html>"}
    assert intel.collect("r.jo", fetch=lambda url: pages.get(url.rstrip("/")))["status"] == intel.STATUS_NO_PRICES
    js_shell = "<html><body><div id='root'></div><script src='/app.js'></script></body></html>"
    assert intel.collect("r.jo", fetch=lambda url: js_shell if url.rstrip("/") == "https://r.jo" else None,
                         render=lambda url: None)["status"] == intel.STATUS_JS


# --- matching products ----------------------------------------------------

def test_names_match_across_spelling_and_arabic_forms_but_not_other_products():
    assert offerings.name_score("Shawarma plate", "Chicken Shawerma") == 1.0
    assert offerings.name_score("منسف", "المنسف الأردني") == 1.0
    assert offerings.name_score("Mansaf", "Maqluba") == 0.0
    assert offerings.name_score("Chicken shawarma", "Beef burger") == 0.0


def test_a_match_needs_the_same_currency_and_a_plausible_price():
    product = {"name": "Mansaf", "price": 6.5, "currency": "JOD"}
    items = [{"name": "منسف لحم", "price": 7.0, "currency": "JOD", "confidence": 0.6},
             {"name": "Mansaf family tray", "price": 45.0, "currency": "JOD", "confidence": 0.9},
             {"name": "Mansaf", "price": 30.0, "currency": "SAR", "confidence": 0.9}]
    assert offerings.best_match(product, items) is None  # no alias, other sizes, other currency
    found = offerings.best_match(product, items, product_aliases=["منسف"])
    assert (found["name"], found["price"], found["match_score"]) == ("منسف لحم", 7.0, 1.0)


# --- relationships ----------------------------------------------------------

def test_relationship_comes_from_evidence_and_says_why():
    q = _query()
    terms = ("mansaf", "shawarma", "middle", "eastern", "منسف", "شاورما")
    assert relevance.classify("Shawerma Reem", None, ["overture:restaurant"], "same_industry", q, terms) == (
        relevance.DIRECT, [{"code": "same_specialty", "term": "shawarma", "where": "name"}])
    assert relevance.classify("Levant", None, ["overture:middle_eastern_restaurant"], "same_industry", q, terms)[0] == relevance.DIRECT
    assert relevance.classify("مطعم شاورما الريم", None, [], "keyword", q, terms)[0] == relevance.DIRECT
    assert relevance.classify("Luna Rossa", None, ["overture:italian_restaurant"], "same_industry", q, terms) == (
        relevance.INDIRECT, [{"code": "same_industry"}])
    assert relevance.classify("Blue Fig", None, ["overture:cafe"], "related_industry", q, terms)[0] == relevance.RELATED
    assert relevance.classify("Some site", None, [], None, q, terms)[0] == relevance.UNVERIFIED
    assert relevance.classify("Luna Rossa", None, [], "same_industry", q, terms, priced_matches=2) == (
        relevance.DIRECT, [{"code": "same_products", "count": 2}])


def test_specialty_words_come_from_the_companys_products_and_the_model():
    relevance._TERMS_CACHE.clear()
    q = _query()
    answer = lambda messages, **kw: '{"en": ["shawarma", "middle eastern", "restaurant"], "ar": ["شاورما", "مشاوي"]}'  # noqa: E731
    terms = relevance.specialty_terms({"business_type": "Restaurant", "product_names": ["Mansaf", "Shawarma plate"]}, q, ask=answer)
    assert {"mansaf", "shawarma", "middle", "eastern", "شاورما", "مشاوي"} <= set(terms) and "restaurant" not in terms


def test_duplicate_listings_of_one_business_merge_into_one():
    a = Candidate(name="Shawerma Reem", source="overture", source_ref="o1", latitude=31.95, longitude=35.91,
                  website="https://reem.jo")
    b = Candidate(name="شاورما ريم Shawerma Reem", source="openstreetmap", source_ref="node/1", latitude=31.9501,
                  longitude=35.9101, website="reem.jo")
    assert len(matching.merge([a, b])) == 1


def test_the_markets_own_category_for_the_specialty_is_learnt_from_named_businesses():
    q = _query()
    named = [(["overture:middle_eastern_restaurant"], relevance.DIRECT), (["overture:middle_eastern_restaurant", "amenity=restaurant"], relevance.DIRECT),
             (["overture:doner_kebab_restaurant"], relevance.DIRECT), (["overture:restaurant"], relevance.DIRECT)]
    learnt = relevance.specialty_categories(named, q)
    assert learnt == {"middle_eastern_restaurant"}  # seen twice; "restaurant" is the industry's own word
    assert relevance.specific_categories(["overture:italian_restaurant", "amenity=restaurant"], q) == {"italian_restaurant"}


def test_profiles_directories_and_short_links_are_not_read_as_the_business_site():
    for url in ("https://www.facebook.com/1", "http://jo.jeeran.com/p/x", "https://vm.tiktok.com/Z", "https://g.co/kgs/x",
                "https://linktr.ee/x", "https://www.talabat.com/jordan/reem"):
        result = intel.collect(url, fetch=lambda u: "<html></html>")
        assert result["status"] == intel.STATUS_NOT_OWN_SITE and result["pages_read"] == []
    assert intel.own_site("https://www.romerogroup.jo/") and intel.own_site("nahdionline.com")
    assert not intel.own_site("http://hotmail.com") and not intel.own_site("www.gmail.com")


def test_a_menu_section_or_the_business_name_completes_a_short_item_name():
    product = {"name": "Margherita pizza", "price": 6.0, "currency": "JOD"}
    assert offerings.best_match(product, [{"name": "Margherita", "section": "Pizza", "price": 7.5, "currency": "JOD"}])["price"] == 7.5
    assert offerings.best_match(product, [{"name": "Margherita", "price": 7.0, "currency": "JOD"}], context="Luigi's Pizza")["price"] == 7.0
    assert offerings.best_match(product, [{"name": "Margherita", "price": 7.0, "currency": "JOD"}], context="Rich Pub") is None


def test_units_and_conditions_are_not_read_as_products_or_currencies():
    # "جم" run together is grams, not Egyptian pounds; "ج.م" is the pound.
    assert intel.text_prices(["حليب أطفال 400 جم"], "SA") == []
    assert intel.text_prices(["فول مدمس 25 ج.م"], "EG")[0]["currency"] == "EGP"
    assert intel.text_prices(["قهوة عربية 18 ⃁"], "SA")[0]["currency"] == "SAR"   # the new riyal sign
    for line in ("Regular price 12.50 SAR", "Add to Cart 12.50 SAR", "أقل من 100 ريال", "التوصيل مجانا للطلبات بقيمة 200 ريال أو أكثر",
                 "4 ريالات للطلبات الأقل من 50 ريال", "– per tablet 15 SAR", "Approximately 20 SAR", "Free shipping on orders over 99 SAR"):
        assert intel.text_prices([line], "SA") == [], line
    # Leading dashes are punctuation, not part of the name; a real item stays.
    assert intel.text_prices(["– Chicken shawarma 2.5 JD", "Order of fries 1.5 JD"], "JO") == [
        {"name": "Chicken shawarma", "price": 2.5, "currency": "JOD"}, {"name": "Order of fries", "price": 1.5, "currency": "JOD"}]


def test_a_theme_demo_page_with_placeholder_text_gives_no_prices():
    demo = ("<html><head><title>Menu</title></head><body><ul><li>Margherita 6 JD</li><li>Lorem ipsum dolor sit amet</li>"
            "<li>Molestie magna 4 JD</li></ul></body></html>")
    assert [f for f in intel.read_page(demo, "https://luigi.jo/menu", "JO")["facts"] if f["kind"] == "product"] == []


def test_a_store_on_a_shared_platform_is_read_only_under_its_own_path():
    assert intel.path_scope("https://take.app/onepieceburger") == "/onepieceburger/"
    assert intel.path_scope("https://r.jo/en/") == "/" and intel.path_scope("https://r.jo/index.html") == "/"
    home = ("<html><body><a href='/onepieceburger/menu'>Menu</a><a href='/nabshop/products'>Products</a>"
            "<a href='/pricing'>Pricing</a></body></html>")
    assert intel.candidate_pages(home, "https://take.app/onepieceburger") == ["https://take.app/onepieceburger/menu"]
    for url in ("https://www.sevenrooms.com/reservations/x", "https://www.opentable.com/r/x", "https://eatapp.co/x"):
        assert not intel.own_site(url)


def test_a_listed_website_of_a_different_business_is_not_read():
    gym = ("<html><head><title>Fitness First Middle East | Gyms</title></head><body>" + "Join the gym today. " * 30 +
           "<a href='/prices'>Membership prices</a></body></html>")
    pages = {"https://www.fitnessfirstme.com": gym}
    fetch = lambda url: pages.get(url.rstrip("/"))  # noqa: E731
    wrong = intel.collect("https://www.fitnessfirstme.com", fetch=fetch, names=["مطعم روحي العقيلي"])
    assert wrong["status"] == intel.STATUS_OTHER_BUSINESS and wrong["facts"] == [] and wrong["pages_read"] == []
    # The business's own words in the address or text confirm it; no names, no check.
    assert intel.collect("https://www.fitnessfirstme.com", fetch=fetch, names=["Fitness First"])["pages_read"]
    assert intel.collect("https://www.fitnessfirstme.com", fetch=fetch)["pages_read"]
    menu = "<html><head><title>Oliva</title></head><body>" + "Fresh Italian food. " * 30 + "</body></html>"
    assert intel.names_the_business(["Oliva Pizza and Pasta"], "http://www.olivajordan.com", menu) is True
    arabic = "<html><body>" + "مطعم روحي للمأكولات الشعبية " * 20 + "</body></html>"
    assert intel.names_the_business(["مطعم روحي العقيلي"], "https://rawhi.jo", arabic) is True
    assert intel.names_the_business(["Restaurant"], "https://x.jo", gym) is None   # nothing distinctive to check


def test_captions_sizes_fees_and_code_are_not_item_names():
    for line in ("The highest price is 20 KWD", "FROM 80 JD", "Starting from 60 USD", "AED 499", "ADD-ON 0.75 JD",
                 "monthly 62 JD", "Add to Wish List 420 EGP", '"price_with_currency": " ", 170 EGP',
                 "The delivery charge is approximately 2.5 JD, depending on the area", "07:42 تم التسليم 1120 AED",
                 "Free Standard Shipping on Orders + Code 50 USD", "Room price in the Umm Qays bed & breakfast starts from . 54 USD",
                 "Stay 6 nights or more and receive a special rate of 149 USD", "Prescription Fee 25 USD",
                 "(first order, generic); up to – (brand) 54 USD"):
        assert intel.text_prices([line], "JO") == [], line
    # A size names a variant of the item above it.
    assert intel.text_prices(["بيتزا خضار", "كبير 6 د.أ"], "JO") == [{"name": "بيتزا خضار - كبير", "price": 6.0, "currency": "JOD"}]
    assert intel.text_prices(['Samsung 55" TV 15000 EGP'], "EG")[0]["price"] == 15000.0
    # The same bare amount on every line is not a price list.
    same = ["Caesar salad 1", "Turkey pizza 1", "Tuna sandwich 1", "Greek salad 1", "Section 2"]
    assert intel.text_prices(same, "JO", menu_page=True) == []


def test_platform_hosts_match_whole_domain_labels_only():
    for url in ("https://alfamarketeg.com", "https://fedex.com", "https://texmexbites.com"):
        assert intel.own_site(url), url
    for url in ("https://g.co/kgs/x", "https://x.com/a", "https://maps.google.com/x", "https://yellowpages-uae.com/x",
                "https://foo.wixsite.com/bar", "https://jo.jeeran.com/p/x", "https://www.yellowpagesjo.com"):
        assert not intel.own_site(url), url


def test_a_sitemap_that_fails_does_not_stop_the_site_being_read():
    home = "<html><head><title>Menu</title></head><body><ul><li>Falafel 0.5 JD</li><li>Hummus 1.25 JD</li></ul></body></html>"

    def fetch(url):
        if "sitemap" in url or "robots" in url:
            raise httpx.ConnectError("down")
        return home if url.rstrip("/") == "https://r.jo" else None
    result = intel.collect("https://r.jo", fetch=fetch)
    assert result["status"] == intel.STATUS_PRICES

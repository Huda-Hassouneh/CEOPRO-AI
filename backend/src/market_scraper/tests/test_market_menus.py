"""Menus and prices outside a competitor's own website (market_menus.py) and the single-product providers built on
them (price_lookup DeliveryMenus / SearchSnippets / MenuPhotos): platform menu data, whose listing it is, photos
that must name the business and hold a price list, and the enrichment facet's reasons. No network: searches,
pages, pictures and OCR are injected."""
import io
import json
from unittest.mock import MagicMock, patch

import pytest

from src.market_scraper import competitor_enrichment as ce
from src.market_scraper import market_menus as mm
from src.market_scraper import web_search
from src.market_scraper.price_lookup import providers
from src.market_scraper.price_lookup.models import ProductContext, ProviderUnavailable

COMPETITOR = {"name": "Al Quds Restaurant", "name_ar": "مطعم القدس", "city": "Amman", "country": "JO", "place_id": "ChIJabc"}

NEXT_DATA = {"props": {"pageProps": {
    "restaurant": {"name": "Al Quds Restaurant", "address": "Rainbow St", "rating": 4.5, "deliveryFee": 1.5,
                   "minimumOrder": {"amount": 5, "currency": "JOD"}, "currency": "JOD"},
    "menu": {"categories": [
        {"name": "Main dishes", "items": [
            {"id": 1, "name": "Mansaf", "price": 8.5, "oldPrice": 10, "description": "Lamb with jameed",
             "choices": [{"name": "Large", "price": 12.0}]},
            {"id": 2, "name": "Maqluba", "price": "7.250", "isAvailable": False},
        ]},
        {"name": "Drinks", "items": [{"id": 3, "name": "Mint lemonade", "price": {"amount": 2.25, "currency": "JOD"}},
                                     {"id": 4, "name": "Tea", "price": {"fractional": 75, "code": "JOD"}}]},
    ]},
}}}


def _listing(title="Al Quds Restaurant - Order online | Talabat", data=NEXT_DATA, body=""):
    return (f"<html><head><title>{title}</title></head><body><h1>{title.split(' - ')[0]}</h1>{body}"
            f"<script id=\"__NEXT_DATA__\" type=\"application/json\">{json.dumps(data)}</script></body></html>")


def _png():
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (300, 200), "white").save(buffer, "PNG")
    return buffer.getvalue()


MENU_TEXT = "Mansaf 8.50 JD\nFalafel sandwich 1.25 JD\nHummus 2.00 JD\nTea 0.50 JD"


def test_platforms_are_recognised_by_domain_and_country_domain():
    assert mm.platform_of("https://www.talabat.com/jordan/restaurant/1/al-quds") == "Talabat"
    assert mm.platform_of("https://deliveroo.ae/menu/dubai/x") == "Deliveroo"
    assert mm.platform_of("https://food.careem.com/x") == "Careem"
    assert mm.platform_of("https://alquds.jo/menu") is None and mm.platform_of("https://nottalabat.com/") is None


def test_platform_menu_data_gives_items_sections_options_discounts_and_fees():
    items, fees = mm.platform_items(_listing(), "JO")
    by_name = {i["name"]: i for i in items}
    assert by_name["Mansaf"]["price"] == 8.5 and by_name["Mansaf"]["original_price"] == 10
    assert by_name["Mansaf"]["discount_percent"] == 15.0 and by_name["Mansaf"]["section"] == "Main dishes"
    assert by_name["Mansaf - Large"]["price"] == 12.0 and by_name["Mansaf - Large"]["price_context"] == "option"
    assert by_name["Maqluba"]["price"] == 7.25 and by_name["Maqluba"]["available"] is False
    assert by_name["Mint lemonade"]["price"] == 2.25 and by_name["Tea"]["price"] == 0.75
    assert all(i["currency"] == "JOD" for i in items)
    assert "Al Quds Restaurant" not in by_name  # the restaurant card (address, rating) is not a dish
    assert {f["name"]: f["price"] for f in fees} == {"Delivery fee": 1.5, "Minimum order": 5}


def test_a_listing_is_read_only_when_it_names_the_business():
    names = [COMPETITOR["name"], COMPETITOR["name_ar"]]
    mine = mm.read_listing(_listing(), "https://www.talabat.com/jordan/restaurant/1/al-quds-restaurant", names, "JO")
    assert mine["verified"] is True and mine["platform"] == "Talabat"
    products = [f for f in mine["facts"] if f["kind"] == "product"]
    assert all(f["channel"] == "delivery" and f["listing_verified"] and f["price_context"] == "delivery_app" for f in products)
    assert any(f["type"] == "fee" and f["name"] == "Delivery fee (Talabat)" for f in products)
    assert next(f for f in products if f["name"] == "Mansaf")["confidence"] == mm.CONFIDENCE_PLATFORM_DATA
    assert next(f for f in products if f["name"] == "Mansaf - Large")["option"] is True

    other = mm.read_listing(_listing("Burger House - Order online"), "https://www.talabat.com/jordan/restaurant/2/burger-house", names, "JO")
    assert other["verified"] is False and other["facts"] == []


def test_a_listing_without_menu_data_falls_back_to_the_page_text():
    body = "<p>Mansaf 8.50 JD</p><p>Hummus 2.00 JD</p><p>Kunafa 3.00 JD</p>"
    listing = mm.read_listing(_listing(data={"x": 1}, body=body), "https://www.zomato.com/amman/al-quds-restaurant/menu",
                              [COMPETITOR["name"]], "JO")
    products = {f["name"]: f for f in listing["facts"] if f["kind"] == "product"}
    assert products["Mansaf"]["price"] == 8.5 and products["Mansaf"]["extracted_by"] == "page_text"
    assert products["Mansaf"]["confidence"] == mm.CONFIDENCE_PLATFORM_TEXT


def test_delivery_listings_search_platforms_and_skip_other_sites_and_businesses():
    results = [web_search.Result("https://alquds.jo/", "Al Quds", ""),  # its own site: the website reader's job
               web_search.Result("https://www.talabat.com/jordan/restaurant/1/al-quds-restaurant", "Al Quds Restaurant | Talabat", ""),
               web_search.Result("https://www.talabat.com/jordan/restaurant/2/burger-house", "Burger House | Talabat", "")]
    pages = {results[1].url: _listing()}
    out = mm.delivery_listings(COMPETITOR, search=lambda q, **k: ("tavily", results), fetch=pages.get, media=lambda u: None)
    assert out["status"] == mm.STATUS_OK
    assert [entry["platform"] for entry in out["listings"]] == ["Talabat"] and out["listings"][0]["items"] >= 5

    def not_configured(query, **kwargs):
        raise web_search.SearchFailed("not_configured")
    assert mm.delivery_listings(COMPETITOR, search=not_configured)["status"] == mm.STATUS_NOT_CONFIGURED


def test_maps_photos_need_a_key_an_approval_and_a_place(monkeypatch):
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    assert mm.maps_photos({**COMPETITOR, "place_id": None})["status"] == mm.STATUS_NO_PLACE
    assert mm.maps_photos(COMPETITOR)["status"] == mm.STATUS_NOT_CONFIGURED
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "k")
    monkeypatch.delenv("PLACES_TERMS_APPROVAL_REFERENCE", raising=False)
    assert mm.maps_photos(COMPETITOR)["status"] == mm.STATUS_APPROVAL_MISSING


def test_maps_photos_keep_only_pictures_with_a_price_list(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "k")
    monkeypatch.setenv("PLACES_TERMS_APPROVAL_REFERENCE", "REF-1")
    texts = iter(["Welcome! Open 9 to 5", MENU_TEXT])
    out = mm.maps_photos(COMPETITOR, photo_urls=lambda pid, key, limit: ["https://lh3.googleusercontent.com/a", "https://lh3.googleusercontent.com/b"],
                         media=lambda url: (_png(), "image/png"), ocr=lambda image: next(texts), ocr_ready=True)
    assert out["status"] == mm.STATUS_OK and out["photos"] == 2
    assert {f["name"] for f in out["facts"]} >= {"Mansaf", "Hummus"}
    fact = out["facts"][0]
    assert fact["channel"] == "maps_photos" and fact["image_url"] == "https://lh3.googleusercontent.com/b"
    assert fact["source_url"] == "https://www.google.com/maps/place/?q=place_id:ChIJabc"  # the listing: photo addresses expire


def test_place_photo_urls_follow_the_places_api_shape():
    calls = []

    def get(url, key, params=None, mask=None):
        calls.append((url, params, mask))
        if url.endswith("/media"):
            return {"photoUri": "https://lh3.googleusercontent.com/p1"}
        return {"photos": [{"name": "places/ChIJabc/photos/P1"}, {"name": "bogus"}]}
    assert mm.place_photo_urls("ChIJabc", "k", 5, get=get) == ["https://lh3.googleusercontent.com/p1"]
    assert calls[0][2] == "photos" and calls[1][0] == "https://places.googleapis.com/v1/places/ChIJabc/photos/P1/media"


def test_web_photos_must_name_the_business_and_hold_prices():
    pictures = [web_search.ImageResult("https://cdn.x.com/a.jpg", "https://blog.x.com/al-quds-restaurant-menu", "Al Quds Restaurant menu"),
                web_search.ImageResult("https://cdn.x.com/b.jpg", None, "Burger House menu"),
                web_search.ImageResult("https://cdn.x.com/c.jpg", None, "menu Amman")]
    texts = {"https://cdn.x.com/a.jpg": MENU_TEXT, "https://cdn.x.com/c.jpg": MENU_TEXT}
    current = {}

    def media(url):
        current["url"] = url
        return _png(), "image/png"
    out = mm.web_photos(COMPETITOR, image_search=lambda q, **k: ("tavily", pictures), media=media,
                        ocr=lambda image: texts.get(current["url"], ""), ocr_ready=True)
    sources = {f["source_url"] for f in out["facts"]}
    # a.jpg names the business; b.jpg names another one (not read); c.jpg is a menu but never says whose: dropped.
    assert sources == {"https://blog.x.com/al-quds-restaurant-menu"}
    assert all(f["channel"] == "web_photos" and f["confidence"] < 0.5 for f in out["facts"])


def test_collect_reports_every_source_and_never_raises():
    def broken(*args, **kwargs):
        raise RuntimeError("boom")
    out = mm.collect(COMPETITOR, search=broken, image_search=lambda q, **k: ("tavily", []), photo_urls=broken,
                     ocr=lambda image: "")
    assert set(out["sources"]) == set(mm.CHANNELS)
    assert out["sources"]["delivery"] == mm.STATUS_FAILED and out["by_channel"]["delivery"] == []


def test_the_market_menus_facet_stores_each_channel_and_explains_the_rest(monkeypatch):
    from src.ai.market_inputs import competitor_intel

    result = {"by_channel": {"delivery": [{"kind": "product", "name": "Mansaf", "price": 8.5}], "maps_photos": [], "web_photos": []},
              "sources": {"delivery": "ok", "maps_photos": "approval_missing", "web_photos": "not_configured"},
              "listings": [{"platform": "Talabat", "status": "read", "items": 1}], "images_read": 0, "images_skipped_no_ocr": 0}
    saved = []
    monkeypatch.setattr(mm, "collect", lambda competitor, deep=False: result)
    monkeypatch.setattr(competitor_intel, "save_channel_facts", lambda conn, t, c, channel, facts: saved.append(channel) or len(facts))
    monkeypatch.setattr(ce, "_write_ledger", MagicMock())
    out = ce.enrich_market_menus(MagicMock(), "t1", "c1", COMPETITOR)
    assert saved == ["delivery"] and out["status"] == ce.STATUS_PARTIAL and out["items_found"] == 1
    assert "Talabat (1 items)" in out["reason_detail"] and "Google Maps photos needs" in out["reason_detail"]

    result.update(by_channel={c: [] for c in mm.CHANNELS}, listings=[],
                  sources={"delivery": "not_configured", "maps_photos": "approval_missing", "web_photos": "not_configured"})
    out = ce.enrich_market_menus(MagicMock(), "t1", "c1", COMPETITOR)
    assert out["status"] == ce.STATUS_BLOCKED and out["reason_code"] == ce.PLATFORM_APPROVAL_MISSING


def test_market_menus_is_paid_and_on_request_only():
    assert ce.FACET_MARKET_MENUS in ce.ENRICHABLE_FACETS and ce.FACET_MARKET_MENUS in ce.PAID_ON_REQUEST_FACETS
    assert ce.FACET_MARKET_MENUS not in ce.ROUTINE_FACETS


# --- single product ------------------------------------------------------------

CTX = ProductContext("p1", "Mansaf", "JO", "JOD", 9.0)


def test_delivery_menus_quotes_the_product_from_platform_listings():
    results = [web_search.Result("https://www.talabat.com/jordan/restaurant/1/al-quds-restaurant", "Al Quds | Talabat", ""),
               web_search.Result("https://example.com/blog", "Best mansaf", "")]
    provider = providers.DeliveryMenus(search=lambda q, **k: ("tavily", results), fetch_page=lambda url: _listing())
    quotes = provider.search(CTX)
    assert {(q.title, q.price) for q in quotes} >= {("Mansaf", 8.5)}
    assert quotes[0].seller == "Al Quds Restaurant (Talabat)" and quotes[0].currency == "JOD"


def test_search_snippets_read_prices_printed_in_results_one_per_site():
    results = [web_search.Result("https://a.jo/x", "Mansaf - 8.50 JD", "Our famous mansaf. Mansaf 9 JD for two."),
               web_search.Result("https://a.jo/y", "Mansaf 7 JD", ""),
               web_search.Result("https://b.jo/", "Menu", "Mansaf 10.00 JD | Tea 0.50 JD")]
    quotes = providers.SearchSnippets(search=lambda q, **k: ("brave", results)).search(CTX)
    assert [(q.seller, q.price) for q in quotes] == [("a.jo", 8.5), ("b.jo", 10.0)]


def test_menu_photos_quote_the_product_from_a_picture():
    pictures = [web_search.ImageResult("https://cdn.x.com/a.jpg", "https://cafe.jo/menu", "menu")]
    provider = providers.MenuPhotos(image_search=lambda q, **k: ("tavily", pictures), fetch_media=lambda url: (_png(), "image/png"),
                                    ocr=lambda image: MENU_TEXT)
    quotes = provider.search(CTX)
    assert [(q.title, q.price, q.seller) for q in quotes] == [("Mansaf", 8.5, "cafe.jo")]

    def not_configured(query, **kwargs):
        raise web_search.SearchFailed("not_configured")
    with pytest.raises(ProviderUnavailable):
        providers.MenuPhotos(image_search=not_configured, ocr=lambda image: "").search(CTX)


def test_image_search_reads_each_providers_shape(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_PROVIDERS", "tavily")
    monkeypatch.setenv("TAVILY_API_KEY", "t")
    fetch = MagicMock(return_value={"images": [{"url": "https://i.com/1.jpg", "description": "Al Quds menu"}, "https://i.com/2.jpg"]})
    name, pictures = web_search.image_search("al quds menu", fetch=fetch)
    assert name == "tavily" and [p.image_url for p in pictures] == ["https://i.com/1.jpg", "https://i.com/2.jpg"]
    assert fetch.call_args.kwargs["json"]["include_images"] is True
    monkeypatch.setenv("WEB_SEARCH_PROVIDERS", "brave")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "b")
    fetch = MagicMock(return_value={"results": [{"url": "https://p.com", "title": "Menu", "properties": {"url": "https://i.com/3.jpg"}}]})
    assert web_search.image_search("x", fetch=fetch)[1] == [web_search.ImageResult("https://i.com/3.jpg", "https://p.com", "Menu")]


def test_groq_vision_is_opt_in_and_sends_the_key_in_a_header(monkeypatch):
    from src.market_scraper.market_discovery import menu_media

    monkeypatch.setattr(menu_media, "VISION_MODE", "fallback")
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "secret")
    monkeypatch.setattr(menu_media, "VISION_PROVIDER", "gemini")
    assert menu_media.vision_engine() is None  # the default provider stays Gemini
    monkeypatch.setattr(menu_media, "VISION_PROVIDER", "groq")
    response = MagicMock()
    response.json.return_value = {"choices": [{"message": {"content": "Mansaf 8.50 JD"}}]}
    from PIL import Image
    with patch("httpx.post", return_value=response) as post, \
            patch("src.market_scraper.provider_billing.metered_request", side_effect=lambda url, send, json_body=None: send()):
        assert menu_media.vision_engine()(Image.new("RGB", (10, 10))) == "Mansaf 8.50 JD"
    assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer secret"} and "secret" not in post.call_args.args[0]
    from src.market_scraper import provider_billing
    assert provider_billing.classify(menu_media.GROQ_VISION_URL)[0] == "groq_vision"


def test_menus_never_lower_the_completeness_score_and_can_fill_the_prices_slot():
    base = {ce.FACET_PROFILE: {"status": ce.STATUS_SUCCEEDED}, ce.FACET_PRICES: {"status": ce.STATUS_FAILED}}
    without = ce._completeness_score(base)  # noqa: SLF001
    assert ce._completeness_score({**base, ce.FACET_MARKET_MENUS: {"status": ce.STATUS_PENDING}}) == without  # noqa: SLF001
    assert ce._completeness_score({**base, ce.FACET_MARKET_MENUS: {"status": ce.STATUS_SUCCEEDED}}) == round(2 / 7 * 100)  # noqa: SLF001


def test_page_data_nested_too_deep_for_the_parser_is_skipped_not_raised():
    """One odd or hostile listing must not stop the other listings (or the price lookup) from being read."""
    deep = "[" * 100_000 + "]" * 100_000
    html = (f'<html><script id="__NEXT_DATA__" type="application/json">{deep}</script>'
            '<script type="application/json">{"menu": {"items": [{"name": "Mansaf", "price": 8.5, "currency": "JOD"}]}}</script></html>')
    items, _fees = mm.platform_items(html, "JO")
    assert [(i["name"], i["price"]) for i in items] == [("Mansaf", 8.5)]

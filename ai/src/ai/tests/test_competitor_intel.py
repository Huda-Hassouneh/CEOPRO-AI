"""Competitor intelligence read from a competitor's own website: products
and prices (structured data and page text), offers, messaging, social
profiles, which of its pages are followed, and that every fact keeps its
page and read time. Pages here are the HTML shapes real shop sites use."""
from src.market_scraper.market_discovery import intel

HOME = """<!doctype html><html><head><title>Habibah Sweets | Nablus kunafa since 1951</title>
<meta name="description" content="Fresh kunafa and Arabic sweets baked daily in downtown Amman.">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Bakery","name":"Habibah Sweets",
 "sameAs":["https://www.instagram.com/habibahsweets","https://www.facebook.com/HabibahSweets"]}</script>
<script>var price = "99 JD";</script></head><body>
<nav><a href="/menu">Our menu</a> <a href="/offers">Offers</a> <a href="/cart">Cart</a>
<a href="https://other.example.com/menu">Partner menu</a> <a href="/about">About us</a> <a href="/menu#top">Menu</a></nav>
<h1>The original Nablus kunafa</h1><h2>Baked fresh every morning</h2>
<div class="promo">Free delivery on orders over 10 JD this week!</div>
<a href="https://twitter.com/intent/tweet?text=x">Share</a>
</body></html>"""

MENU = """<html><head><script type="application/ld+json">{"@context":"https://schema.org","@type":"Menu","hasMenuSection":[
{"@type":"MenuSection","name":"Kunafa","hasMenuItem":[
 {"@type":"MenuItem","name":"Kunafa Nabulsieh","offers":{"@type":"Offer","price":"3.50","priceCurrency":"JOD"}},
 {"@type":"MenuItem","name":"Kunafa Khishneh","offers":{"@type":"Offer","price":"3.75","priceCurrency":"JOD"}}]}]}</script></head>
<body><ul><li>Baklava box (1 kg) 12 JD</li><li>معمول بالتمر</li><li>4.25 دينار</li>
<li>Kunafa Nabulsieh - 3.50 JD</li><li>خصم 20% على علب البقلاوة</li></ul></body></html>"""

OFFERS = "<html><body><p>Ramadan offer: buy 2 get 1 free on maamoul boxes</p><p>Kunafa Nabulsieh 3.25 JD</p></body></html>"


def _site(pages):
    def fetch(url):
        return pages.get(url.rstrip("/"))
    return fetch


def test_products_prices_offers_and_messages_are_read_with_their_page():
    result = intel.collect("https://habibah.jo", fetch=_site({
        "https://habibah.jo": HOME, "https://habibah.jo/menu": MENU, "https://habibah.jo/offers": OFFERS}))
    assert result["pages_read"] == ["https://habibah.jo", "https://habibah.jo/menu", "https://habibah.jo/offers"]
    products = {(f["name"], f["price"], f["currency"], f["confidence"]) for f in result["facts"] if f["kind"] == "product"}
    assert ("Kunafa Nabulsieh", 3.5, "JOD", intel.CONFIDENCE_STRUCTURED) in products
    assert ("Kunafa Khishneh", 3.75, "JOD", intel.CONFIDENCE_STRUCTURED) in products
    assert ("Baklava box (1 kg)", 12.0, "JOD", intel.CONFIDENCE_TEXT) in products
    assert ("معمول بالتمر", 4.25, "JOD", intel.CONFIDENCE_TEXT) in products  # name on the line above the amount
    # The same product published at another price on another page is kept: a conflict to show.
    assert ("Kunafa Nabulsieh", 3.25, "JOD", intel.CONFIDENCE_TEXT) in products
    # Nothing from inside <script> is read as a price.
    assert not any(p[1] == 99.0 for p in products)
    promos = [f["text"] for f in result["facts"] if f["kind"] == "promotion"]
    assert "Free delivery on orders over 10 JD this week!" in promos
    assert "خصم 20% على علب البقلاوة" in promos and any("buy 2 get 1" in p for p in promos)
    messages = [f["text"] for f in result["facts"] if f["kind"] == "message"]
    assert messages[:3] == ["Habibah Sweets | Nablus kunafa since 1951",
                            "Fresh kunafa and Arabic sweets baked daily in downtown Amman.", "The original Nablus kunafa"]
    social = [f["url"] for f in result["facts"] if f["kind"] == "social"]
    assert social == ["https://www.instagram.com/habibahsweets", "https://www.facebook.com/HabibahSweets"]
    for fact in result["facts"]:
        assert fact["source_url"].startswith("https://habibah.jo") and fact["retrieved_at"]
    menu_fact = next(f for f in result["facts"] if f["kind"] == "product" and f["price"] == 3.75)
    assert menu_fact["source_url"] == "https://habibah.jo/menu"


def test_only_the_sites_own_product_pages_are_followed():
    pages = intel.candidate_pages(HOME, "https://habibah.jo/")
    assert pages == ["https://habibah.jo/menu", "https://habibah.jo/offers"]  # no cart, no other site, no about, once each


def test_a_blocked_or_unreachable_site_adds_nothing():
    blocked = intel.collect("habibah.jo", fetch=lambda url: None)
    assert blocked["facts"] == [] and blocked["error"] == "not_allowed" and blocked["pages_blocked"] == 1

    import httpx

    def down(url):
        raise httpx.ConnectError("no route")

    unreachable = intel.collect("https://habibah.jo", fetch=down)
    assert unreachable["facts"] == [] and unreachable["error"] == "unreachable"


def test_text_prices_need_a_name_and_a_currency():
    lines = ["Call 0790000000", "Open 9 to 5", "Kunafa 3.5 JD", "Total: JD 12", "Delivery fee 1 JD", "2026"]
    assert intel.text_prices(lines) == [{"name": "Kunafa", "price": 3.5, "currency": "JOD"}]


def test_analysis_answers_with_trailing_text_are_read_and_bad_ones_retried(monkeypatch):
    from src.ai.market_inputs import competitor_analysis
    from src.ai.rag import llm_client

    assert competitor_analysis._parse_json('Sure: {"trends": []} hope this helps {"x": 1}') == {"trends": []}
    answers = iter(['{"trends": [{"text": "a", "evidence": [1]} "watch": []}', '{"trends": [], "watch": []}'])
    calls = []

    def model(messages, **kwargs):
        calls.append(1)
        kwargs["usage_out"]["total_tokens"] = 100
        return next(answers)

    monkeypatch.setattr(llm_client, "chat_completion", model)
    conn = __import__("unittest.mock").mock.MagicMock()
    assert competitor_analysis._ask(conn, "t", "system", [{"text": "x", "url": None}], "en") == {"trends": [], "watch": []}
    assert len(calls) == 2

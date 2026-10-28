"""
Live-DB tests (skipped unless AI_TEST_DATABASE_URL is set) for the two ways
a business now feeds market data in by itself, found missing in
first-customer acceptance testing: competitor prices it observed, and its
own customers' reviews. Before this, both tables were written only by the
scraper, so pricing and sentiment never worked without it.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import psycopg2
import pytest

from src.ai.market_inputs import competitor_prices, customer_reviews
from src.ai.pricing import data_access as pricing_data
from src.ai.pricing.pipeline import run_price_recommendation
from src.ai.routers.products import create_product

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


def _company(conn, country="JO", currency="JOD") -> str:
    tenant_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, 'Inputs Co', %s, %s);",
            (tenant_id, country, currency),
        )
    return tenant_id


def _tracked_competitor(conn, tenant_id, name="Rival Market") -> str:
    competitor_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO global_competitors (global_competitor_id, competitor_name, visibility, added_by_tenant_id, is_manufacturer) "
            "VALUES (%s, %s, 'PRIVATE', %s, FALSE);",
            (competitor_id, f"{name} {competitor_id[:6]}", tenant_id),
        )
        cursor.execute("INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked) VALUES (%s, %s, TRUE);", (tenant_id, competitor_id))
    return competitor_id


# --- competitor prices --------------------------------------------------------

def test_recorded_prices_drive_a_real_recommendation_using_each_competitors_latest_price(conn):
    tenant_id = _company(conn)
    product = create_product(conn, tenant_id, None, {"en": "Olive Oil 1L"}, None, None, None, 9.5, 6.2, "JOD")
    rival_a, rival_b = _tracked_competitor(conn, tenant_id, "A"), _tracked_competitor(conn, tenant_id, "B")
    now = datetime.now(timezone.utc)
    # rival A was checked twice: only its latest price (8.00) may count
    competitor_prices.record_competitor_price(conn, tenant_id, rival_a, product["product_id"], Decimal("7.00"), "JOD", observed_at=now - timedelta(days=3))
    competitor_prices.record_competitor_price(conn, tenant_id, rival_a, product["product_id"], Decimal("8.00"), "JOD", observed_at=now - timedelta(days=1))
    competitor_prices.record_competitor_price(conn, tenant_id, rival_b, product["product_id"], Decimal("8.50"), "JOD")
    conn.commit()

    prices = pricing_data.load_competitor_prices(conn, tenant_id, product["product_id"], "JOD")
    assert sorted(p["price_found"] for p in prices) == [8.0, 8.5]
    from src.ai.market_inputs.market_structure import build
    observed = build(conn, tenant_id)['product_prices'][0]['prices']
    assert all(p['provenance']=='manual' and p['provider_verified'] is False for p in observed)

    result = run_price_recommendation(conn, tenant_id, product["product_id"])
    assert result["matched_competitor_count"] == 2
    assert result["action"] == "lower" and result["suggested_price"] == 8.25  # mean(8.00, 8.50), JOD 3 dp


def test_recording_a_price_for_an_untracked_competitor_or_unknown_product_is_rejected(conn):
    tenant_id, other = _company(conn), _company(conn)
    product = create_product(conn, tenant_id, None, {"en": "Widget"}, None, None, None, 5, None, "JOD")
    theirs = _tracked_competitor(conn, other)
    with pytest.raises(competitor_prices.NotFound):
        competitor_prices.record_competitor_price(conn, tenant_id, theirs, product["product_id"], Decimal("4"), "JOD")
    mine = _tracked_competitor(conn, tenant_id)
    with pytest.raises(competitor_prices.NotFound):
        competitor_prices.record_competitor_price(conn, tenant_id, mine, str(uuid.uuid4()), Decimal("4"), "JOD")


# --- customer reviews -------------------------------------------------------------

def test_reviews_import_in_arabic_and_french_headers_links_products_and_dedupes(conn):
    tenant_id = _company(conn, "MA", "MAD")
    create_product(conn, tenant_id, None, {"en": "Argan Oil 100ml"}, None, None, None, 120, None, "MAD")
    headers = ["التاريخ", "التقييم", "التعليق", "المنتج", "المصدر"]
    rows = [
        {"التاريخ": "05/09/2026", "التقييم": "٥", "التعليق": "منتج ممتاز", "المنتج": "Argan Oil 100ml", "المصدر": "Google Maps"},
        {"التاريخ": "06/09/2026", "التقييم": "4/5", "التعليق": "خدمة جيدة", "المنتج": "", "المصدر": "Facebook"},
        {"التاريخ": "07/09/2026", "التقييم": "2", "التعليق": "", "المنتج": "", "المصدر": ""},
        {"التاريخ": "08/09/2026", "التقييم": "3", "التعليق": "عادي", "المنتج": "Unknown soap", "المصدر": ""},
    ]
    summary = customer_reviews.import_reviews(conn, tenant_id, headers, rows, day_first=True)
    conn.commit()
    assert (summary.imported, summary.skipped, summary.linked_to_products) == (3, 1, 1)
    assert summary.unmatched_products == ["Unknown soap"]

    again = customer_reviews.import_reviews(conn, tenant_id, headers, rows, day_first=True)
    conn.commit()
    assert (again.imported, again.duplicates) == (0, 3)

    reviews = customer_reviews.list_reviews(conn, tenant_id)
    by_text = {r["text"]: r for r in reviews}
    assert by_text["منتج ممتاز"]["rating"] == 5.0 and by_text["منتج ممتاز"]["product_name"] == "Argan Oil 100ml"
    assert by_text["خدمة جيدة"]["rating"] == 4.0 and by_text["خدمة جيدة"]["platform"] == "Facebook"
    assert by_text["منتج ممتاز"]["review_date"].startswith("2026-09-05")  # day-first locale

    french = customer_reviews.import_reviews(conn, tenant_id, ["Date", "Note", "Avis"], [{"Date": "2026-09-09", "Note": "8/10", "Avis": "Très bon accueil"}])
    assert french.imported == 1
    assert {r["text"]: r["rating"] for r in customer_reviews.list_reviews(conn, tenant_id)}["Très bon accueil"] == 4.0


def test_reviews_file_without_a_text_column_is_reported_not_silently_empty(conn):
    tenant_id = _company(conn)
    summary = customer_reviews.import_reviews(conn, tenant_id, ["date", "stars"], [{"date": "2026-09-01", "stars": "5"}])
    assert summary.missing_columns == ["review text"] and summary.imported == 0


def test_reviews_are_tenant_isolated(conn):
    mine, theirs = _company(conn), _company(conn)
    customer_reviews.import_reviews(conn, theirs, ["review"], [{"review": "their private feedback"}])
    conn.commit()
    assert customer_reviews.list_reviews(conn, mine) == []


@pytest.mark.parametrize("raw,day_first,expected", [
    ("2026-09-02", True, "2026-09-02"),   # ISO stays ISO even for a day-first locale
    ("2026/09/02", True, "2026-09-02"),
    ("02/09/2026", True, "2026-09-02"),
    ("09/02/2026", False, "2026-09-02"),
    ("٠٢/٠٩/٢٠٢٦", True, "2026-09-02"),
    ("2999-01-01", True, None),           # future -> unknown, never trusted
    ("not a date", True, None),
])
def test_parse_review_date(raw, day_first, expected):
    parsed = customer_reviews.parse_review_date(raw, day_first)
    assert (parsed.date().isoformat() if parsed else None) == expected


@pytest.mark.parametrize("raw,expected", [
    ("5", 5.0), ("4,5", 4.5), ("٤", 4.0), ("4/5", 4.0), ("8/10", 4.0), ("9", 4.5), ("★★★☆☆", 3.0), ("", None), ("great", None), ("11", None),
])
def test_parse_rating(raw, expected):
    assert customer_reviews.parse_rating(raw) == expected

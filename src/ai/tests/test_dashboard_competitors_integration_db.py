"""
Integration tests for dashboard/competitors.py against a real PostgreSQL
instance. Same convention as every other live-DB test in this package:
skipped unless AI_TEST_DATABASE_URL is set.
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

from src.ai.dashboard.competitors import get_competitor_directory
from src.ai.pricing.competitor_classification import TIER_CANDIDATE, TIER_RELEVANT, TIER_STRATEGIC

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


def _insert_company(conn) -> str:
    tenant_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, %s, 'JO', 'JOD');",
            (tenant_id, f"Test Co {tenant_id[:8]}"),
        )
    return tenant_id


def _insert_product(conn, tenant_id, name, current_price=50.0) -> str:
    product_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, %s, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name}), current_price),
        )
    return product_id


def _insert_tracked_competitor(
    conn, tenant_id, name, tier, match_rate, website_url=None, is_tracked=True, classified_at=None,
) -> str:
    competitor_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO global_competitors (global_competitor_id, competitor_name, website_url, visibility, added_by_tenant_id, is_manufacturer) "
            "VALUES (%s, %s, %s, 'PRIVATE', %s, FALSE);",
            (competitor_id, name, website_url, tenant_id),
        )
        cursor.execute(
            "INSERT INTO tenant_competitors (tenant_id, global_competitor_id, tier, product_match_rate, is_tracked, is_confirmed_competitor, classified_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s);",
            (tenant_id, competitor_id, tier, match_rate, is_tracked, is_tracked, classified_at),
        )
    return competitor_id


def _insert_competitor_review_with_sentiment(conn, tenant_id, competitor_id, positive_probability, negative_probability):
    review_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO reviews (review_id, tenant_id, subject_type, competitor_id, source_platform, review_text) "
            "VALUES (%s, %s, 'COMPETITOR', %s, 'GOOGLE', 'A review.');",
            (review_id, tenant_id, competitor_id),
        )
    from src.ai.sentiment.evidence import insert_sentiment_result
    neutral_probability = 1.0 - positive_probability - negative_probability
    insert_sentiment_result(
        conn, review_id, tenant_id, "POSITIVE", positive_probability, neutral_probability,
        negative_probability, 0.9, "test-model-v1",
    )


def _map_product_with_price(conn, tenant_id, product_id, competitor_id, your_price, their_price):
    source_id = str(uuid.uuid4())
    mapping_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE products SET current_price = %s WHERE product_id = %s;",
            (your_price, product_id),
        )
        cursor.execute(
            "INSERT INTO data_sources (source_id, tenant_id, source_name, source_type) VALUES (%s, %s, 'Test Source', 'WEB_SCRAPE');",
            (source_id, tenant_id),
        )
        cursor.execute(
            "INSERT INTO competitor_product_mappings (mapping_id, tenant_id, global_competitor_id, product_id, source_id) "
            "VALUES (%s, %s, %s, %s, %s);",
            (mapping_id, tenant_id, competitor_id, product_id, source_id),
        )
        cursor.execute(
            "INSERT INTO competitor_prices (tenant_id, mapping_id, scraped_price, currency) VALUES (%s, %s, %s, 'JOD');",
            (tenant_id, mapping_id, their_price),
        )


def test_returns_empty_groups_for_a_tenant_with_no_competitors(conn):
    tenant_id = _insert_company(conn)
    conn.commit()
    assert get_competitor_directory(conn, tenant_id) == {"strategic": [], "relevant": [], "possible": []}


def test_strategic_competitor_shows_name_tier_website_and_exact_overlap_pct(conn):
    tenant_id = _insert_company(conn)
    _insert_tracked_competitor(
        conn, tenant_id, "SparkFun Electronics", TIER_STRATEGIC, match_rate=0.75,
        website_url="https://sparkfun.com",
    )
    conn.commit()

    directory = get_competitor_directory(conn, tenant_id)

    assert directory["relevant"] == []
    assert len(directory["strategic"]) == 1
    row = directory["strategic"][0]
    assert row["name"] == "SparkFun Electronics"
    assert row["tier"] == TIER_STRATEGIC
    assert row["website_url"] == "https://sparkfun.com"
    assert row["overlap_pct"] == 75.0
    assert "price_comparisons" not in row


def test_relevant_competitor_shows_name_tier_website_and_price_comparisons(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    competitor_id = _insert_tracked_competitor(
        conn, tenant_id, "PiShop US", TIER_RELEVANT, match_rate=0.33,
        website_url="https://pishop.us",
    )
    conn.commit()
    _map_product_with_price(conn, tenant_id, product_id, competitor_id, your_price=60.0, their_price=45.0)
    conn.commit()

    directory = get_competitor_directory(conn, tenant_id)

    assert directory["strategic"] == []
    assert len(directory["relevant"]) == 1
    row = directory["relevant"][0]
    assert row["name"] == "PiShop US"
    assert row["tier"] == TIER_RELEVANT
    assert row["website_url"] == "https://pishop.us"
    assert "overlap_pct" not in row
    assert row["price_comparisons"] == [
        {"product_name": "Widget", "your_price": 60.0, "their_price": 45.0, "currency": "JOD"},
    ]


def test_omits_untracked_candidate_tier_competitors_entirely(conn):
    tenant_id = _insert_company(conn)
    _insert_tracked_competitor(
        conn, tenant_id, "Excluded Manufacturer", TIER_CANDIDATE, match_rate=0.0, is_tracked=False,
    )
    conn.commit()

    directory = get_competitor_directory(conn, tenant_id)
    assert directory == {"strategic": [], "relevant": [], "possible": []}


def test_groups_are_sorted_alphabetically_by_name(conn):
    tenant_id = _insert_company(conn)
    _insert_tracked_competitor(conn, tenant_id, "Zebra Corp", TIER_STRATEGIC, match_rate=0.9)
    _insert_tracked_competitor(conn, tenant_id, "Acme Inc", TIER_STRATEGIC, match_rate=0.8)
    conn.commit()

    directory = get_competitor_directory(conn, tenant_id)
    assert [row["name"] for row in directory["strategic"]] == ["Acme Inc", "Zebra Corp"]


def test_last_updated_is_none_when_never_classified(conn):
    tenant_id = _insert_company(conn)
    _insert_tracked_competitor(conn, tenant_id, "Rival Co", TIER_STRATEGIC, match_rate=0.9)
    conn.commit()

    row = get_competitor_directory(conn, tenant_id)["strategic"][0]
    assert row["last_updated"] is None


def test_last_updated_reflects_the_real_classified_at_timestamp(conn):
    tenant_id = _insert_company(conn)
    classified_at = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    _insert_tracked_competitor(conn, tenant_id, "Rival Co", TIER_STRATEGIC, match_rate=0.9, classified_at=classified_at)
    conn.commit()

    row = get_competitor_directory(conn, tenant_id)["strategic"][0]
    assert row["last_updated"] == classified_at.isoformat()


def test_market_sentiment_label_is_none_with_no_analyzed_reviews(conn):
    tenant_id = _insert_company(conn)
    _insert_tracked_competitor(conn, tenant_id, "Rival Co", TIER_STRATEGIC, match_rate=0.9)
    conn.commit()

    row = get_competitor_directory(conn, tenant_id)["strategic"][0]
    assert row["market_sentiment_label"] is None


def test_market_sentiment_label_reflects_real_analyzed_reviews(conn):
    tenant_id = _insert_company(conn)
    competitor_id = _insert_tracked_competitor(conn, tenant_id, "Rival Co", TIER_STRATEGIC, match_rate=0.9)
    conn.commit()
    _insert_competitor_review_with_sentiment(conn, tenant_id, competitor_id, positive_probability=0.8, negative_probability=0.1)
    conn.commit()

    row = get_competitor_directory(conn, tenant_id)["strategic"][0]
    assert row["market_sentiment_label"] == "Positive"


def test_price_competitiveness_is_none_with_no_real_price_observation(conn):
    tenant_id = _insert_company(conn)
    _insert_tracked_competitor(conn, tenant_id, "Rival Co", TIER_STRATEGIC, match_rate=0.9)
    conn.commit()

    row = get_competitor_directory(conn, tenant_id)["strategic"][0]
    assert row["price_competitiveness"] is None


def test_market_activity_defaults_to_low_with_no_price_history(conn):
    tenant_id = _insert_company(conn)
    _insert_tracked_competitor(conn, tenant_id, "Rival Co", TIER_STRATEGIC, match_rate=0.9)
    conn.commit()

    row = get_competitor_directory(conn, tenant_id)["strategic"][0]
    assert row["market_activity"] == "Low"


def test_market_activity_reflects_real_detected_price_changes(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    competitor_id = _insert_tracked_competitor(conn, tenant_id, "Rival Co", TIER_STRATEGIC, match_rate=0.9)
    conn.commit()
    _map_product_with_price(conn, tenant_id, product_id, competitor_id, your_price=100.0, their_price=90.0)
    conn.commit()
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT mapping_id FROM competitor_product_mappings WHERE tenant_id = %s AND global_competitor_id = %s;",
            (tenant_id, competitor_id),
        )
        mapping_id = cursor.fetchone()[0]
        now = datetime.now(timezone.utc)
        for i, price in enumerate([90.0, 85.0, 80.0]):
            cursor.execute(
                "INSERT INTO competitor_prices (tenant_id, mapping_id, scraped_price, currency, observed_at) "
                "VALUES (%s, %s, %s, 'JOD', %s);",
                (tenant_id, mapping_id, price, now - timedelta(days=3 - i)),
            )
    conn.commit()

    row = get_competitor_directory(conn, tenant_id)["strategic"][0]
    assert row["market_activity"] == "High"


def test_price_competitiveness_reflects_a_real_price_match_for_a_strategic_competitor(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    competitor_id = _insert_tracked_competitor(conn, tenant_id, "Rival Co", TIER_STRATEGIC, match_rate=0.9)
    conn.commit()
    _map_product_with_price(conn, tenant_id, product_id, competitor_id, your_price=100.0, their_price=100.0)
    conn.commit()

    row = get_competitor_directory(conn, tenant_id)["strategic"][0]
    assert row["price_competitiveness"] == 10.0  # priced exactly at market


def test_relevance_score_is_none_with_no_real_signals_at_all(conn):
    """No price comparisons, no analyzed reviews, no price observations -
    a genuinely blank competitor gets an honest None, not a score
    manufactured from the display-only "Low" activity default."""
    tenant_id = _insert_company(conn)
    _insert_tracked_competitor(conn, tenant_id, "Rival Co", TIER_STRATEGIC, match_rate=0.9)
    conn.commit()

    row = get_competitor_directory(conn, tenant_id)["strategic"][0]
    assert row["relevance_score"] is None
    assert row["strengths"] == []
    assert row["weaknesses"] == []


def test_relevance_score_is_real_when_price_and_sentiment_signals_exist(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    competitor_id = _insert_tracked_competitor(conn, tenant_id, "Rival Co", TIER_STRATEGIC, match_rate=0.9)
    conn.commit()
    _map_product_with_price(conn, tenant_id, product_id, competitor_id, your_price=100.0, their_price=100.0)
    _insert_competitor_review_with_sentiment(conn, tenant_id, competitor_id, positive_probability=0.9, negative_probability=0.05)
    conn.commit()

    row = get_competitor_directory(conn, tenant_id)["strategic"][0]
    assert row["relevance_score"] is not None
    assert 0 <= row["relevance_score"] <= 100
    assert "Priced competitively against the market" in row["strengths"]
    assert "Positive customer sentiment" in row["strengths"]


def test_weaknesses_reflect_real_poor_signals(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    competitor_id = _insert_tracked_competitor(conn, tenant_id, "Rival Co", TIER_STRATEGIC, match_rate=0.9)
    conn.commit()
    _map_product_with_price(conn, tenant_id, product_id, competitor_id, your_price=100.0, their_price=60.0)
    _insert_competitor_review_with_sentiment(conn, tenant_id, competitor_id, positive_probability=0.05, negative_probability=0.9)
    conn.commit()

    row = get_competitor_directory(conn, tenant_id)["strategic"][0]
    assert "Priced less competitively than the market" in row["weaknesses"]
    assert "Negative customer sentiment" in row["weaknesses"]
    assert row["strengths"] == []


def test_summary_line_is_factual_and_tier_specific(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    strategic_id = _insert_tracked_competitor(conn, tenant_id, "Strategic Co", TIER_STRATEGIC, match_rate=0.75)
    relevant_id = _insert_tracked_competitor(conn, tenant_id, "Relevant Co", TIER_RELEVANT, match_rate=0.3)
    conn.commit()
    _map_product_with_price(conn, tenant_id, product_id, relevant_id, your_price=100.0, their_price=90.0)
    conn.commit()

    directory = get_competitor_directory(conn, tenant_id)
    assert directory["strategic"][0]["summary_line"] == "Strategic competitor — 75% product overlap with your catalog."
    assert directory["relevant"][0]["summary_line"] == "Relevant competitor — 1 of your product matched for price comparison."


def test_directory_is_ordered_by_confidence_best_first_and_carries_details(conn):
    tenant_id = _insert_company(conn)
    low = _insert_tracked_competitor(conn, tenant_id, "Aardvark Low", TIER_RELEVANT, 0.2)
    high = _insert_tracked_competitor(conn, tenant_id, "Zebra High", TIER_RELEVANT, 0.2)
    mid = _insert_tracked_competitor(conn, tenant_id, "Mid Co", TIER_RELEVANT, 0.2)
    with conn.cursor() as cursor:
        for competitor_id, score, label in ((low, 30.0, "Low"), (high, 88.0, "High"), (mid, 55.0, "Medium")):
            cursor.execute(
                "UPDATE tenant_competitors SET confidence_score = %s, confidence_label = %s, "
                "confidence_reasons = %s, distance_km = 2.34, category_similarity = 0.67 "
                "WHERE tenant_id = %s AND global_competitor_id = %s;",
                (score, label, json.dumps(["Closely related category"]), tenant_id, competitor_id),
            )
        cursor.execute(
            "UPDATE global_competitors SET category_path = %s, address = 'Rainbow St, Amman', phone = '+962 6 1', "
            "rating = 4.5, rating_count = 120 WHERE global_competitor_id = %s;",
            (["food", "snacks", "pizza"], high),
        )

    directory = get_competitor_directory(conn, tenant_id, separate_weak_leads=True)
    relevant = directory["relevant"]

    # the Low-confidence row with nothing in common is a weak lead, kept apart
    assert [c["name"] for c in relevant] == ["Zebra High", "Mid Co"]
    assert [c["name"] for c in directory["possible"]] == ["Aardvark Low"]
    top = relevant[0]
    assert top["confidence_label"] == "High" and top["confidence_score"] == 88.0
    assert top["category"] == "food > snacks > pizza"
    assert top["category_match_pct"] == 67
    assert top["address"] == "Rainbow St, Amman" and top["phone"] == "+962 6 1"
    assert top["rating"] == 4.5 and top["rating_count"] == 120
    assert top["distance_km"] == 2.3
    assert top["confidence_reasons"] == ["Closely related category"]
    assert top["found_via"] == "MANUAL"
    assert top["confidence_summary"].startswith("High confidence relevant competitor")
    assert top["summary_line"].startswith("Relevant competitor — ")  # original wording is a stable contract


def test_weak_low_confidence_leads_are_listed_apart_from_relevant(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    weak = _insert_tracked_competitor(conn, tenant_id, "Weak Lead", TIER_RELEVANT, 0.0)
    solid = _insert_tracked_competitor(conn, tenant_id, "Solid Co", TIER_RELEVANT, 0.3)
    unscored = _insert_tracked_competitor(conn, tenant_id, "Unscored Co", TIER_RELEVANT, 0.1)
    low_but_sells_your_product = _insert_tracked_competitor(conn, tenant_id, "Overlap Co", TIER_RELEVANT, 0.3)
    conn.commit()
    _map_product_with_price(conn, tenant_id, product_id, low_but_sells_your_product, your_price=10.0, their_price=9.0)
    with conn.cursor() as cursor:
        for cid, label, score in ((weak, "Low", 20.0), (solid, "Medium", 55.0), (low_but_sells_your_product, "Low", 30.0)):
            cursor.execute(
                "UPDATE tenant_competitors SET confidence_label = %s, confidence_score = %s "
                "WHERE tenant_id = %s AND global_competitor_id = %s;", (label, score, tenant_id, cid),
            )
    conn.commit()

    directory = get_competitor_directory(conn, tenant_id, separate_weak_leads=True)

    assert [c["name"] for c in directory["possible"]] == ["Weak Lead"]
    assert {c["name"] for c in directory["relevant"]} == {"Solid Co", "Unscored Co", "Overlap Co"}


# --- backward-compatible contract: new behaviours are opt-in ---

def _seed_scored(conn, tenant_id):
    ids = {}
    for name, label, score, distance in (
        ("Alpha", "High", 90.0, 1.0), ("Bravo", "Medium", 60.0, 5.0), ("Charlie", "Low", 20.0, 30.0), ("Delta", "Low", 10.0, None),
    ):
        cid = _insert_tracked_competitor(conn, tenant_id, name, TIER_RELEVANT, 0.1)
        ids[name] = cid
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE tenant_competitors SET confidence_label = %s, confidence_score = %s, distance_km = %s "
                "WHERE tenant_id = %s AND global_competitor_id = %s;", (label, score, distance, tenant_id, cid),
            )
    return ids


def test_by_default_weak_leads_stay_in_relevant_so_the_original_contract_holds(conn):
    tenant_id = _insert_company(conn)
    _seed_scored(conn, tenant_id)
    directory = get_competitor_directory(conn, tenant_id)
    assert [c["name"] for c in directory["relevant"]] == ["Alpha", "Bravo", "Charlie", "Delta"]  # best first
    assert directory["possible"] == []
    assert set(directory) == {"strategic", "relevant", "possible"}


def test_opting_in_splits_out_weak_leads(conn):
    tenant_id = _insert_company(conn)
    _seed_scored(conn, tenant_id)
    directory = get_competitor_directory(conn, tenant_id, separate_weak_leads=True)
    assert [c["name"] for c in directory["relevant"]] == ["Alpha", "Bravo"]
    assert [c["name"] for c in directory["possible"]] == ["Charlie", "Delta"]


def test_min_confidence_filter(conn):
    tenant_id = _insert_company(conn)
    _seed_scored(conn, tenant_id)
    names = [c["name"] for c in get_competitor_directory(conn, tenant_id, min_confidence=50)["relevant"]]
    assert names == ["Alpha", "Bravo"]


def test_max_distance_filter_excludes_unknown_distance(conn):
    tenant_id = _insert_company(conn)
    _seed_scored(conn, tenant_id)
    names = [c["name"] for c in get_competitor_directory(conn, tenant_id, max_distance_km=10)["relevant"]]
    assert names == ["Alpha", "Bravo"]


def test_pagination_applies_after_ordering(conn):
    tenant_id = _insert_company(conn)
    _seed_scored(conn, tenant_id)
    page = get_competitor_directory(conn, tenant_id, limit=2, offset=1)["relevant"]
    assert [c["name"] for c in page] == ["Bravo", "Charlie"]


def test_every_original_contract_field_is_still_present(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    strategic = _insert_tracked_competitor(conn, tenant_id, "S Co", TIER_STRATEGIC, 0.8, website_url="https://s.example")
    relevant = _insert_tracked_competitor(conn, tenant_id, "R Co", TIER_RELEVANT, 0.2)
    conn.commit()
    _map_product_with_price(conn, tenant_id, product_id, relevant, your_price=10.0, their_price=9.0)
    directory = get_competitor_directory(conn, tenant_id)

    original_common = {
        "name", "tier", "website_url", "market_sentiment_label", "price_competitiveness", "last_updated",
        "market_activity", "relevance_score", "strengths", "weaknesses", "summary_line",
    }
    assert original_common <= set(directory["strategic"][0]) and "overlap_pct" in directory["strategic"][0]
    assert original_common <= set(directory["relevant"][0]) and "price_comparisons" in directory["relevant"][0]

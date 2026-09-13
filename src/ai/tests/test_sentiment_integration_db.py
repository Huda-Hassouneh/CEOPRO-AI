"""
Integration test for the sentiment pipeline against a real PostgreSQL
instance running the actual init_schema.sql. Same convention as
test_pricing_integration_db.py: skipped unless AI_TEST_DATABASE_URL is set.
Uses model.classify patched with a deterministic fake to keep this fast and
independent of the real (opt-in, network-downloading) model - the real
model's own correctness is covered separately in test_sentiment_model_real.py.
"""

import json
import os
import uuid
from unittest.mock import patch

import psycopg2
import pytest

from src.ai.sentiment import data_access, pipeline
from src.ai.sentiment.model import SentimentPrediction

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


@pytest.fixture
def seeded_tenant_and_product(conn):
    tenant_id = str(uuid.uuid4())
    product_id = str(uuid.uuid4())

    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO companies (tenant_id, business_name, country_code, primary_currency)
            VALUES (%s, 'Sentiment Test Co', 'JO', 'JOD');
            """,
            (tenant_id,),
        )
        cursor.execute(
            """
            INSERT INTO products (product_id, tenant_id, product_name, current_price, currency)
            VALUES (%s, %s, %s, 20.00, 'JOD');
            """,
            (product_id, tenant_id, json.dumps({"en": "Sunscreen SPF 50"})),
        )
    conn.commit()

    return tenant_id, product_id


def _insert_review(conn, tenant_id: str, product_id: str, text: str, source_status: str = "ALLOWED") -> str:
    review_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO reviews
                (review_id, tenant_id, subject_type, product_id, review_text, review_language, source_status, source_platform)
            VALUES (%s, %s, 'PRODUCT', %s, %s, 'en', %s, 'GOOGLE');
            """,
            (review_id, tenant_id, product_id, text, source_status),
        )
    conn.commit()
    return review_id


def _fake_predictions(count: int, label: str = "positive") -> list:
    probs = {"positive": 0.1, "neutral": 0.1, "negative": 0.1}
    probs[label] = 0.8
    return [
        SentimentPrediction(
            label=label,
            positive_probability=probs["positive"],
            neutral_probability=probs["neutral"],
            negative_probability=probs["negative"],
            confidence=0.8,
            model_version="fake-model-v1",
        )
        for _ in range(count)
    ]


def test_load_unanalyzed_reviews_reads_seeded_rows(conn, seeded_tenant_and_product):
    tenant_id, product_id = seeded_tenant_and_product
    _insert_review(conn, tenant_id, product_id, "Great product")

    reviews = data_access.load_unanalyzed_reviews(conn, tenant_id)
    assert len(reviews) == 1
    assert reviews[0]["review_text"] == "Great product"
    assert reviews[0]["subject_type"] == "PRODUCT"


def test_load_unanalyzed_reviews_excludes_blocked_source_status(conn, seeded_tenant_and_product):
    tenant_id, product_id = seeded_tenant_and_product
    _insert_review(conn, tenant_id, product_id, "Should be excluded", source_status="BLOCKED")

    reviews = data_access.load_unanalyzed_reviews(conn, tenant_id)
    assert reviews == []


def _insert_competitor(conn, tenant_id: str, name: str) -> str:
    competitor_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO global_competitors (global_competitor_id, competitor_name, visibility, added_by_tenant_id, is_manufacturer) "
            "VALUES (%s, %s, 'PRIVATE', %s, FALSE);",
            (competitor_id, name, tenant_id),
        )
        cursor.execute(
            "INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked) VALUES (%s, %s, TRUE);",
            (tenant_id, competitor_id),
        )
    return competitor_id


def _insert_competitor_review_with_sentiment(conn, tenant_id: str, competitor_id: str, label: str, positive: float, negative: float):
    from src.ai.sentiment.evidence import insert_sentiment_result

    review_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO reviews (review_id, tenant_id, subject_type, competitor_id, source_platform, review_text) "
            "VALUES (%s, %s, 'COMPETITOR', %s, 'FACEBOOK', 'test review');",
            (review_id, tenant_id, competitor_id),
        )
    insert_sentiment_result(conn, review_id, tenant_id, label, positive, 0.1, negative, 0.9, "test-model-v1")


def test_load_aggregate_sentiment_by_competitor_matches_the_single_subject_query(conn, seeded_tenant_and_product):
    """
    The real fix: this batched function must return the exact same
    per-competitor numbers load_aggregate_sentiment(subject_type=
    "COMPETITOR", subject_id=...) already computes one competitor at a
    time - just in one round trip for every tracked competitor instead
    of one round trip each.
    """
    tenant_id, _ = seeded_tenant_and_product
    competitor_a = _insert_competitor(conn, tenant_id, "Rival A")
    competitor_b = _insert_competitor(conn, tenant_id, "Rival B")
    conn.commit()

    _insert_competitor_review_with_sentiment(conn, tenant_id, competitor_a, "POSITIVE", 0.8, 0.1)
    _insert_competitor_review_with_sentiment(conn, tenant_id, competitor_a, "NEGATIVE", 0.1, 0.7)
    _insert_competitor_review_with_sentiment(conn, tenant_id, competitor_b, "POSITIVE", 0.9, 0.05)
    conn.commit()

    by_competitor = data_access.load_aggregate_sentiment_by_competitor(conn, tenant_id)

    expected_a = data_access.load_aggregate_sentiment(conn, tenant_id, "COMPETITOR", competitor_a)
    expected_b = data_access.load_aggregate_sentiment(conn, tenant_id, "COMPETITOR", competitor_b)

    assert by_competitor[competitor_a] == expected_a
    assert by_competitor[competitor_b] == expected_b


def test_load_aggregate_sentiment_by_competitor_omits_competitors_with_no_analyzed_reviews(conn, seeded_tenant_and_product):
    tenant_id, _ = seeded_tenant_and_product
    _insert_competitor(conn, tenant_id, "Untracked Sentiment Rival")
    conn.commit()

    by_competitor = data_access.load_aggregate_sentiment_by_competitor(conn, tenant_id)

    assert by_competitor == {}


def test_classify_and_store_reviews_writes_sentiment_results_and_excludes_reanalysis(conn, seeded_tenant_and_product):
    tenant_id, product_id = seeded_tenant_and_product
    _insert_review(conn, tenant_id, product_id, "Great product")
    _insert_review(conn, tenant_id, product_id, "Terrible experience")

    with patch.object(pipeline.model, "classify", return_value=_fake_predictions(2)):
        result = pipeline.classify_and_store_reviews(conn, tenant_id)

    assert result == {"status": "OK", "analyzed_count": 2, "failed_count": 0}

    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM sentiment_results WHERE tenant_id = %s;", (tenant_id,))
        assert cursor.fetchone()[0] == 2

    # Already-analyzed reviews must not be picked up again.
    remaining = data_access.load_unanalyzed_reviews(conn, tenant_id)
    assert remaining == []


def test_classify_and_store_reviews_one_bad_review_does_not_block_the_others_against_real_db(
    conn, seeded_tenant_and_product
):
    """
    The real fix, against a real transaction/SAVEPOINT (not a mock): one
    review whose insert fails at the database level must not abort the
    whole transaction and silently drop the OTHER reviews in the same
    batch - before the SAVEPOINT isolation, a single failed INSERT would
    have left the transaction aborted for every statement after it.
    """
    tenant_id, product_id = seeded_tenant_and_product
    _insert_review(conn, tenant_id, product_id, "Great product")
    _insert_review(conn, tenant_id, product_id, "Terrible experience")

    reviews = data_access.load_unanalyzed_reviews(conn, tenant_id)
    good_predictions = _fake_predictions(2)

    real_insert = pipeline.evidence.insert_sentiment_result

    def _flaky_insert(conn, review_id, *args):
        if review_id == reviews[0]["review_id"]:
            raise ValueError("simulated bad review")
        return real_insert(conn, review_id, *args)

    with patch.object(pipeline.model, "classify", return_value=good_predictions), \
         patch.object(pipeline.evidence, "insert_sentiment_result", side_effect=_flaky_insert):
        result = pipeline.classify_and_store_reviews(conn, tenant_id)

    assert result == {"status": "OK", "analyzed_count": 1, "failed_count": 1}

    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM sentiment_results WHERE tenant_id = %s;", (tenant_id,))
        assert cursor.fetchone()[0] == 1  # the good review's result really did commit

    # The failing review is still unanalyzed and eligible for a future retry.
    remaining = data_access.load_unanalyzed_reviews(conn, tenant_id)
    assert len(remaining) == 1
    assert remaining[0]["review_id"] == reviews[0]["review_id"]


def test_get_subject_sentiment_summary_with_no_reviews_writes_unknown_evidence(conn, seeded_tenant_and_product):
    tenant_id, product_id = seeded_tenant_and_product

    result = pipeline.get_subject_sentiment_summary(conn, tenant_id, "PRODUCT", product_id)

    assert result["status"] == "UNKNOWN"
    with conn.cursor() as cursor:
        cursor.execute("SELECT category FROM evidence_records WHERE evidence_id = %s;", (result["evidence_id"],))
        assert cursor.fetchone()[0] == "UNKNOWN"


def test_get_subject_sentiment_summary_below_threshold_flags_low_sample_size_against_real_db(
    conn, seeded_tenant_and_product
):
    tenant_id, product_id = seeded_tenant_and_product
    for _ in range(3):  # below cold_start.MIN_SAMPLE_SIZE (10)
        _insert_review(conn, tenant_id, product_id, "Great product")

    with patch.object(pipeline.model, "classify", return_value=_fake_predictions(3)):
        pipeline.classify_and_store_reviews(conn, tenant_id)

    result = pipeline.get_subject_sentiment_summary(conn, tenant_id, "PRODUCT", product_id)

    assert result["status"] == "OK"
    assert result["sample_size"]["status"] == "LOW_SAMPLE_SIZE"
    with conn.cursor() as cursor:
        cursor.execute("SELECT explanation_text FROM evidence_records WHERE evidence_id = %s;", (result["evidence_id"],))
        assert "LOW SAMPLE SIZE" in cursor.fetchone()[0]


def test_get_subject_sentiment_summary_at_threshold_reports_ok_against_real_db(conn, seeded_tenant_and_product):
    tenant_id, product_id = seeded_tenant_and_product
    n = pipeline.cold_start.MIN_SAMPLE_SIZE
    for _ in range(n):
        _insert_review(conn, tenant_id, product_id, "Great product")

    with patch.object(pipeline.model, "classify", return_value=_fake_predictions(n, label="positive")):
        pipeline.classify_and_store_reviews(conn, tenant_id)

    result = pipeline.get_subject_sentiment_summary(conn, tenant_id, "PRODUCT", product_id)

    assert result["status"] == "OK"
    assert result["sample_size"]["status"] == "OK"
    assert result["label_counts"]["positive"] == n
    assert result["sentiment_score"] > 0
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT category, confidence_score FROM evidence_records WHERE evidence_id = %s;", (result["evidence_id"],)
        )
        category, confidence_score = cursor.fetchone()
        assert category == "FACT"
        assert float(confidence_score) == pipeline.CONFIDENCE_SUFFICIENT_SAMPLE

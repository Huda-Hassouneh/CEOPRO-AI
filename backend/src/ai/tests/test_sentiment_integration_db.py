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
import threading
import uuid
from unittest.mock import patch

import psycopg2
import pytest

from src.ai import db
from src.ai.sentiment import data_access, pipeline
from src.ai.sentiment.model import SentimentPrediction
from src.ai.tests.test_rls_integration_db import _ensure_role_key, _insert_user

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


def test_concurrent_classification_cannot_consume_the_last_allowance_twice(
    conn, seeded_tenant_and_product, monkeypatch
):
    """Both workers see the final unit before either reserves it.

    The atomic usage reservation must allow one persisted sentiment result,
    return a truthful plan-limit result for the other worker, and retain a
    counter of exactly one.
    """
    tenant_id, product_id = seeded_tenant_and_product
    _insert_review(conn, tenant_id, product_id, "One available review")
    with conn.cursor() as cursor:
        role_key = _ensure_role_key(cursor)
        user_id = _insert_user(cursor, "sentiment-race")
        cursor.execute(
            "INSERT INTO tenant_users (tenant_id,user_id,role_key) VALUES (%s,%s,%s)",
            (tenant_id, user_id, role_key),
        )
        cursor.execute(
            "INSERT INTO tenant_entitlement_overrides "
            "(tenant_id,feature_code,limit_value,contract_ref,approved_by,reason) "
            "VALUES (%s,'sentiment_analysis',1,'test-fixture','test-runner','atomic quota regression')",
            (tenant_id,),
        )
    conn.commit()

    loaded = threading.Barrier(2)
    actual_loader = pipeline.data_access.load_unanalyzed_reviews

    def load_before_both_reserve(*args, **kwargs):
        result = actual_loader(*args, **kwargs)
        loaded.wait(timeout=10)
        return result

    monkeypatch.setattr(pipeline.data_access, "load_unanalyzed_reviews", load_before_both_reserve)
    monkeypatch.setattr(
        pipeline.model,
        "classify_or_unavailable",
        lambda texts, *args, **kwargs: _fake_predictions(len(texts)),
    )
    results, errors = [], []

    def run_worker():
        worker_conn = db.app_role_connection(tenant_id, user_id)
        try:
            results.append(pipeline.classify_and_store_reviews(worker_conn, tenant_id, batch_size=1))
        except Exception as exc:  # captured so pytest reports assertion context below
            worker_conn.rollback()
            errors.append(exc)
        finally:
            worker_conn.close()

    workers = [threading.Thread(target=run_worker) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=15)

    assert not any(worker.is_alive() for worker in workers), "classification workers did not finish"
    assert errors == []
    assert sorted(result["status"] for result in results) == ["OK", "PLAN_LIMIT"]
    assert sum(result["analyzed_count"] for result in results) == 1
    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM sentiment_results WHERE tenant_id=%s", (tenant_id,))
        assert cursor.fetchone()[0] == 1
        cursor.execute(
            "SELECT used FROM tenant_usage_counters "
            "WHERE tenant_id=%s AND feature_code='sentiment_analysis' "
            "AND period_start=date_trunc('month', CURRENT_DATE)::date",
            (tenant_id,),
        )
        assert cursor.fetchone()[0] == 1


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

    assert result == {"status": "OK", "analyzed_count": 2, "failed_count": 0, "method": "model"}

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

    assert result == {"status": "OK", "analyzed_count": 1, "failed_count": 1, "method": "model"}

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


def test_unreachable_model_falls_back_to_the_customers_star_rating(conn, seeded_tenant_and_product, monkeypatch):
    """No network to the model host: rated reviews get their sentiment from the
    star rating (marked as such), unrated reviews stay unanalyzed."""
    from src.ai.sentiment import model as sentiment_model

    tenant_id, product_id = seeded_tenant_and_product
    unrated = _insert_review(conn, tenant_id, product_id, "No stars on this one")
    rated = {}
    for stars, text in [(5, "Excellent oil"), (3, "It was okay"), (1, "Arrived broken")]:
        review_id = _insert_review(conn, tenant_id, product_id, text)
        with conn.cursor() as cursor:
            cursor.execute("UPDATE reviews SET review_rating = %s WHERE review_id = %s;", (stars, review_id))
        rated[review_id] = stars
    conn.commit()

    def _no_model(*_args, **_kwargs):
        raise OSError("We couldn't connect to 'https://huggingface.co'")

    monkeypatch.setattr(sentiment_model, "classify", _no_model)
    monkeypatch.setattr(sentiment_model, "_unavailable_until", 0.0)
    result = pipeline.classify_and_store_reviews(conn, tenant_id)
    assert result == {"status": "OK", "analyzed_count": 3, "failed_count": 0, "method": "star_rating"}

    with conn.cursor() as cursor:
        cursor.execute("SELECT review_id::text, sentiment_label, model_version FROM sentiment_results WHERE tenant_id = %s;", (tenant_id,))
        stored = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}
    expected = {5: "positive", 3: "neutral", 1: "negative"}
    assert {rid: stored[rid][0].lower() for rid in rated} == {rid: expected[stars] for rid, stars in rated.items()}
    assert all(version == sentiment_model.RATING_MODEL_VERSION for _, version in stored.values())
    assert unrated not in stored

    # Nothing rated left: the batch reports the model as unavailable, writes nothing.
    assert pipeline.classify_and_store_reviews(conn, tenant_id)["status"] == "MODEL_UNAVAILABLE"

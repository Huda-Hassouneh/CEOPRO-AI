"""
Integration test for the MPI pipeline against a real PostgreSQL instance
running the actual init_schema.sql. Same convention as
test_sentiment_integration_db.py: skipped unless AI_TEST_DATABASE_URL is set.
Inserts sentiment_results rows directly (not via the real classifier) - the
classifier's own correctness is covered in src/ai/tests/test_sentiment_*.py;
this test is about the MPI's own SQL/scoring logic against the real schema.
"""

import os
import uuid
from datetime import date, datetime, timedelta, timezone

import psycopg2
import pytest

from src.ai.mpi import data_access, pipeline

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
def seeded_tenant_product_and_competitor(conn):
    tenant_id = str(uuid.uuid4())
    product_id = str(uuid.uuid4())
    competitor_id = str(uuid.uuid4())

    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO companies (tenant_id, business_name, country_code, primary_currency)
            VALUES (%s, 'MPI Test Co', 'JO', 'JOD');
            """,
            (tenant_id,),
        )
        cursor.execute(
            """
            INSERT INTO products (product_id, tenant_id, product_name, current_price, currency)
            VALUES (%s, %s, 'Sunscreen SPF 50', 20.00, 'JOD');
            """,
            (product_id, tenant_id),
        )
        cursor.execute(
            """
            INSERT INTO competitors (competitor_id, tenant_id, competitor_name, country_code)
            VALUES (%s, %s, 'Rival Pharmacy', 'SA');
            """,
            (competitor_id, tenant_id),
        )
    conn.commit()

    return tenant_id, product_id, competitor_id


def _insert_scored_review(
    conn, tenant_id: str, subject_type: str, label: str, positive: float, negative: float,
    product_id: str = None, competitor_id: str = None, days_ago: int = 0, collection_method: str = "PUBLIC_API",
) -> str:
    review_id = str(uuid.uuid4())
    review_date = datetime.now(timezone.utc) - timedelta(days=days_ago)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO reviews
                (review_id, tenant_id, subject_type, product_id, competitor_id, review_text,
                 review_language, review_date, collection_method, source_status)
            VALUES (%s, %s, %s, %s, %s, 'test review text', 'en', %s, %s, 'ALLOWED');
            """,
            (review_id, tenant_id, subject_type, product_id, competitor_id, review_date, collection_method),
        )
        cursor.execute(
            """
            INSERT INTO sentiment_results
                (review_id, tenant_id, label, positive_probability, neutral_probability, negative_probability,
                 confidence, model_version)
            VALUES (%s, %s, %s, %s, 0.05, %s, 0.9, 'test-model');
            """,
            (review_id, tenant_id, label, positive, negative),
        )
    conn.commit()
    return review_id


def test_load_scored_reviews_reads_seeded_rows(conn, seeded_tenant_product_and_competitor):
    tenant_id, product_id, _ = seeded_tenant_product_and_competitor
    _insert_scored_review(conn, tenant_id, "PRODUCT", "positive", 0.9, 0.05, product_id=product_id)

    reviews = data_access.load_scored_reviews(conn, tenant_id, "PRODUCT", product_id)
    assert len(reviews) == 1
    assert reviews[0]["label"] == "positive"
    assert reviews[0]["collection_method"] == "PUBLIC_API"


def test_load_country_context_for_business_and_competitor(conn, seeded_tenant_product_and_competitor):
    tenant_id, product_id, competitor_id = seeded_tenant_product_and_competitor

    assert data_access.load_country_context(conn, tenant_id, "BUSINESS") == "JO"
    assert data_access.load_country_context(conn, tenant_id, "PRODUCT", product_id) == "JO"
    assert data_access.load_country_context(conn, tenant_id, "COMPETITOR", competitor_id) == "SA"


def test_get_subject_mpi_with_no_reviews_writes_unknown_evidence(conn, seeded_tenant_product_and_competitor):
    tenant_id, product_id, _ = seeded_tenant_product_and_competitor

    result = pipeline.get_subject_mpi(conn, tenant_id, "PRODUCT", product_id)

    assert result["status"] == "UNKNOWN"
    with conn.cursor() as cursor:
        cursor.execute("SELECT category FROM evidence_records WHERE evidence_id = %s;", (result["evidence_id"],))
        assert cursor.fetchone()[0] == "UNKNOWN"


def test_get_subject_mpi_below_threshold_flags_low_sample_size_against_real_db(conn, seeded_tenant_product_and_competitor):
    tenant_id, product_id, _ = seeded_tenant_product_and_competitor
    _insert_scored_review(conn, tenant_id, "PRODUCT", "positive", 0.9, 0.05, product_id=product_id)

    result = pipeline.get_subject_mpi(conn, tenant_id, "PRODUCT", product_id, as_of=date.today())

    assert result["status"] == "OK"
    assert result["sample_size"]["status"] == "LOW_SAMPLE_SIZE"
    with conn.cursor() as cursor:
        cursor.execute("SELECT explanation_text FROM evidence_records WHERE evidence_id = %s;", (result["evidence_id"],))
        assert "LOW SAMPLE SIZE" in cursor.fetchone()[0]


def test_get_subject_mpi_sufficient_sample_writes_fact_with_country_context(conn, seeded_tenant_product_and_competitor):
    tenant_id, product_id, _ = seeded_tenant_product_and_competitor
    n = pipeline.cold_start.MIN_SAMPLE_SIZE
    for _ in range(n):
        _insert_scored_review(conn, tenant_id, "PRODUCT", "positive", 0.9, 0.05, product_id=product_id)

    result = pipeline.get_subject_mpi(conn, tenant_id, "PRODUCT", product_id, as_of=date.today())

    assert result["status"] == "OK"
    assert result["sample_size"]["status"] == "OK"
    assert result["mpi"] > 50
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT category, country_context FROM evidence_records WHERE evidence_id = %s;", (result["evidence_id"],)
        )
        category, country_context = cursor.fetchone()
        assert category == "FACT"
        assert country_context == "JO"


def test_compare_subjects_against_real_db_refuses_below_volume_floor(conn, seeded_tenant_product_and_competitor):
    tenant_id, product_id, competitor_id = seeded_tenant_product_and_competitor
    _insert_scored_review(conn, tenant_id, "PRODUCT", "positive", 0.9, 0.05, product_id=product_id)
    for _ in range(15):
        _insert_scored_review(conn, tenant_id, "COMPETITOR", "negative", 0.05, 0.9, competitor_id=competitor_id)

    comparison = pipeline.compare_subjects(
        conn, tenant_id, ("PRODUCT", product_id), ("COMPETITOR", competitor_id), min_volume_for_comparison=10
    )

    assert comparison.comparable is False
    assert comparison.difference is None

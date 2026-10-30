"""
Integration test for the MPI pipeline against a real PostgreSQL instance
running the actual init_schema.sql. Same convention as
test_sentiment_integration_db.py: skipped unless AI_TEST_DATABASE_URL is set.
Inserts sentiment_results rows directly (not via the real classifier) - the
classifier's own correctness is covered in src/ai/tests/test_sentiment_*.py;
this test is about the MPI's own SQL/scoring logic against the real schema.
"""

import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone

import psycopg2
import pytest

from src.ai import db
from src.ai.mpi import data_access, pipeline, scoring

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
    global_competitor_id = str(uuid.uuid4())

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
            VALUES (%s, %s, %s, 20.00, 'JOD');
            """,
            (product_id, tenant_id, json.dumps({"en": "Sunscreen SPF 50"})),
        )
        cursor.execute(
            """
            INSERT INTO global_competitors (global_competitor_id, competitor_name, country_code, visibility, added_by_tenant_id)
            VALUES (%s, 'Rival Pharmacy', 'SA', 'PRIVATE', %s);
            """,
            (global_competitor_id, tenant_id),
        )
        cursor.execute(
            """
            INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked)
            VALUES (%s, %s, TRUE);
            """,
            (tenant_id, global_competitor_id),
        )
    conn.commit()

    return tenant_id, product_id, global_competitor_id


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
                 review_language, review_date, collection_method, source_status, source_platform)
            VALUES (%s, %s, %s, %s, %s, 'test review text', 'en', %s, %s, 'ALLOWED', 'GOOGLE');
            """,
            (review_id, tenant_id, subject_type, product_id, competitor_id, review_date, collection_method),
        )
        # sentiment_results.sentiment_label/sentiment_score are Final_schema.sql's
        # NOT NULL columns - populated the same way src/ai/sentiment/evidence.py
        # does (upper-cased label, positive-minus-negative score).
        cursor.execute(
            """
            INSERT INTO sentiment_results
                (review_id, tenant_id, sentiment_label, sentiment_score, positive_probability,
                 neutral_probability, negative_probability, confidence, model_version)
            VALUES (%s, %s, %s, %s, %s, 0.05, %s, 0.9, 'test-model');
            """,
            (review_id, tenant_id, label.upper(), round(positive - negative, 4), positive, negative),
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
    assert reviews[0]["source_platform"] == "GOOGLE"
    assert reviews[0]["sentiment_model_version"] == "test-model"


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


def test_all_three_subject_scopes_validate_and_persist_attributed_evidence(
    conn, seeded_tenant_product_and_competitor
):
    tenant_id, product_id, competitor_id = seeded_tenant_product_and_competitor
    review_ids = {
        "BUSINESS": _insert_scored_review(conn, tenant_id, "BUSINESS", "positive", .8, .1),
        "PRODUCT": _insert_scored_review(conn, tenant_id, "PRODUCT", "neutral", .4, .4, product_id=product_id),
        "COMPETITOR": _insert_scored_review(
            conn, tenant_id, "COMPETITOR", "negative", .1, .8, competitor_id=competitor_id
        ),
    }
    subjects = (("BUSINESS", None), ("PRODUCT", product_id), ("COMPETITOR", competitor_id))

    for subject_type, subject_id in subjects:
        result = pipeline.get_subject_mpi(conn, tenant_id, subject_type, subject_id)
        assert result["status"] == "OK"
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT source_record_ids FROM evidence_records WHERE evidence_id = %s",
                (result["evidence_id"],),
            )
            evidence_payload = cursor.fetchone()[0]
        expected_review_id = review_ids[subject_type]
        assert evidence_payload["review_provenance"][0]["review_id"] == expected_review_id
        assert evidence_payload["review_provenance"][0]["sentiment_model_version"] == "test-model"
        assert evidence_payload["subject_type"] == subject_type


def test_subject_validation_hides_cross_tenant_or_missing_entities_without_evidence(
    conn, seeded_tenant_product_and_competitor
):
    tenant_id, _, _ = seeded_tenant_product_and_competitor
    other_tenant = str(uuid.uuid4())
    foreign_product = str(uuid.uuid4())
    deleted_product = str(uuid.uuid4())
    foreign_competitor = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, 'Other MPI Tenant', 'US', 'USD')",
            (other_tenant,),
        )
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, 12, 'USD')",
            (foreign_product, other_tenant, json.dumps({"en": "Private Product"})),
        )
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, 9, 'USD')",
            (deleted_product, tenant_id, json.dumps({"en": "Deleted Product"})),
        )
        cursor.execute("UPDATE products SET deleted_at=CURRENT_TIMESTAMP WHERE product_id=%s", (deleted_product,))
        cursor.execute(
            "INSERT INTO global_competitors "
            "(global_competitor_id, competitor_name, country_code, visibility, added_by_tenant_id) "
            "VALUES (%s, 'Private Foreign MPI Competitor', 'US', 'PRIVATE', %s)",
            (foreign_competitor, other_tenant),
        )
        cursor.execute(
            "INSERT INTO tenant_competitors (tenant_id, global_competitor_id) VALUES (%s, %s)",
            (other_tenant, foreign_competitor),
        )
        cursor.execute("SELECT COUNT(*) FROM evidence_records WHERE tenant_id = %s", (tenant_id,))
        before = cursor.fetchone()[0]
    conn.commit()

    for subject_type, subject_id in (
        ("PRODUCT", foreign_product),
        ("PRODUCT", deleted_product),
        ("PRODUCT", str(uuid.uuid4())),
        ("COMPETITOR", foreign_competitor),
        ("BUSINESS", other_tenant),
    ):
        with pytest.raises(data_access.SubjectNotFoundError):
            pipeline.get_subject_mpi(conn, tenant_id, subject_type, subject_id)

    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM evidence_records WHERE tenant_id = %s", (tenant_id,))
        assert cursor.fetchone()[0] == before


def test_mpi_excludes_disallowed_quarantined_blank_and_future_reviews(
    conn, seeded_tenant_product_and_competitor
):
    tenant_id, product_id, _ = seeded_tenant_product_and_competitor
    allowed_id = _insert_scored_review(conn, tenant_id, "PRODUCT", "positive", .9, .05, product_id=product_id)
    blocked_id = _insert_scored_review(conn, tenant_id, "PRODUCT", "negative", .05, .9, product_id=product_id)
    quarantined_id = _insert_scored_review(conn, tenant_id, "PRODUCT", "negative", .05, .9, product_id=product_id)
    blank_id = _insert_scored_review(conn, tenant_id, "PRODUCT", "negative", .05, .9, product_id=product_id)
    future_id = _insert_scored_review(conn, tenant_id, "PRODUCT", "negative", .05, .9, product_id=product_id)
    foreign_source_review_id = _insert_scored_review(
        conn, tenant_id, "PRODUCT", "negative", .05, .9, product_id=product_id
    )
    foreign_source_tenant = str(uuid.uuid4())
    foreign_source_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, 'Foreign Source Tenant', 'DE', 'EUR')",
            (foreign_source_tenant,),
        )
        cursor.execute(
            "INSERT INTO data_sources (source_id, tenant_id, source_name, source_type) "
            "VALUES (%s, %s, 'Foreign review source', 'GENERIC_API')",
            (foreign_source_id, foreign_source_tenant),
        )
        cursor.execute("UPDATE reviews SET source_status='BLOCKED' WHERE review_id=%s", (blocked_id,))
        cursor.execute("UPDATE reviews SET safety_status='QUARANTINED' WHERE review_id=%s", (quarantined_id,))
        cursor.execute("UPDATE reviews SET review_text='   ' WHERE review_id=%s", (blank_id,))
        cursor.execute("UPDATE reviews SET source_id=%s WHERE review_id=%s", (foreign_source_id, foreign_source_review_id))
        cursor.execute(
            "UPDATE reviews SET review_date=CURRENT_TIMESTAMP + INTERVAL '1 hour' WHERE review_id=%s",
            (future_id,),
        )
    conn.commit()

    reviews = data_access.load_scored_reviews(conn, tenant_id, "PRODUCT", product_id)
    assert [review["review_id"] for review in reviews] == [allowed_id]


def test_mpi_ignores_malformed_sentiment_probabilities(conn, seeded_tenant_product_and_competitor):
    tenant_id, product_id, _ = seeded_tenant_product_and_competitor
    valid_id = _insert_scored_review(conn, tenant_id, "PRODUCT", "positive", .9, .05, product_id=product_id)
    malformed_id = _insert_scored_review(conn, tenant_id, "PRODUCT", "negative", .05, .9, product_id=product_id)
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE sentiment_results SET positive_probability = -0.25 WHERE review_id = %s",
            (malformed_id,),
        )
    conn.commit()

    reviews = data_access.load_scored_reviews(conn, tenant_id, "PRODUCT", product_id)
    assert [review["review_id"] for review in reviews] == [valid_id]


def test_unique_sentiment_identity_prevents_duplicate_review_contributions(
    conn, seeded_tenant_product_and_competitor
):
    tenant_id, product_id, _ = seeded_tenant_product_and_competitor
    review_id = _insert_scored_review(conn, tenant_id, "PRODUCT", "positive", .9, .05, product_id=product_id)
    with conn.cursor() as cursor:
        with pytest.raises(psycopg2.IntegrityError):
            cursor.execute(
                "INSERT INTO sentiment_results "
                "(tenant_id, review_id, sentiment_label, sentiment_score, positive_probability, "
                "neutral_probability, negative_probability, confidence, model_version) "
                "VALUES (%s, %s, 'POSITIVE', .85, .9, .05, .05, .9, 'test-model-duplicate')",
                (tenant_id, review_id),
            )
    conn.rollback()
    reviews = data_access.load_scored_reviews(conn, tenant_id, "PRODUCT", product_id)
    assert [review["review_id"] for review in reviews] == [review_id]


def test_restricted_application_role_observes_tenant_scoped_mpi_rows(
    conn, seeded_tenant_product_and_competitor
):
    tenant_id, product_id, _ = seeded_tenant_product_and_competitor
    _insert_scored_review(conn, tenant_id, "PRODUCT", "positive", .9, .05, product_id=product_id)
    other_tenant = str(uuid.uuid4())
    other_product = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO users (user_id, email, password_hash) VALUES (%s, %s, 'test-hash')",
            (user_id, f"mpi-rls-{user_id}@example.com"),
        )
        cursor.execute(
            "INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, 'owner')",
            (tenant_id, user_id),
        )
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, 'RLS Other Tenant', 'GB', 'GBP')",
            (other_tenant,),
        )
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, 10, 'GBP')",
            (other_product, other_tenant, json.dumps({"en": "Other Product"})),
        )
    conn.commit()

    # Use the production restricted-role connection constructor, not the
    # administrative fixture connection, for the isolation assertion.
    scoped = db.app_role_connection(tenant_id, user_id)
    try:
        with scoped.cursor() as cursor:
            cursor.execute("SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")
            role_name, is_superuser, bypass_rls = cursor.fetchone()
            assert role_name == "ceopro_app"
            assert is_superuser is False
            assert bypass_rls is False
            cursor.execute("SELECT product_id::text FROM products WHERE product_id=%s", (other_product,))
            assert cursor.fetchone() is None
        own_result = pipeline.get_subject_mpi(scoped, tenant_id, "PRODUCT", product_id)
        assert own_result["status"] == "OK"
        with scoped.cursor() as cursor:
            cursor.execute(
                "SELECT source_record_ids->>'subject_type' FROM evidence_records WHERE evidence_id=%s",
                (own_result["evidence_id"],),
            )
            assert cursor.fetchone()[0] == "PRODUCT"
        with pytest.raises(data_access.SubjectNotFoundError):
            pipeline.get_subject_mpi(scoped, tenant_id, "PRODUCT", other_product)
        scoped.rollback()
    finally:
        scoped.close()


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


@pytest.mark.parametrize('excluded', ['blocked', 'quarantined', 'blank', 'future', 'missing_sentiment', 'malformed'])
def test_only_ineligible_reviews_persist_unknown_current_behavior(conn, seeded_tenant_product_and_competitor, excluded):
    tenant, product, _ = seeded_tenant_product_and_competitor
    review = _insert_scored_review(conn, tenant, 'PRODUCT', 'positive', .9, .05, product_id=product)
    statements = {
        'blocked': "UPDATE reviews SET source_status='BLOCKED' WHERE review_id=%s",
        'quarantined': "UPDATE reviews SET safety_status='QUARANTINED' WHERE review_id=%s",
        'blank': "UPDATE reviews SET review_text='   ' WHERE review_id=%s",
        'future': "UPDATE reviews SET review_date=CURRENT_TIMESTAMP + INTERVAL '1 day' WHERE review_id=%s",
        'missing_sentiment': 'DELETE FROM sentiment_results WHERE review_id=%s',
        'malformed': 'UPDATE sentiment_results SET positive_probability=-.1 WHERE review_id=%s',
    }
    with conn.cursor() as q:
        q.execute(statements[excluded], (review,))
        # A rating is not a fallback for absent/malformed analyzed sentiment.
        q.execute('UPDATE reviews SET review_rating=5 WHERE review_id=%s', (review,))
    conn.commit()
    result = pipeline.get_subject_mpi(conn, tenant, 'PRODUCT', product, as_of=date(2020, 1, 1))
    assert result['status'] == 'UNKNOWN'
    with conn.cursor() as q:
        q.execute('SELECT category,source_record_ids,confidence_score FROM evidence_records WHERE evidence_id=%s', (result['evidence_id'],))
        category, payload, confidence = q.fetchone()
    assert category == 'UNKNOWN' and confidence is None
    assert payload == dict(subject_type='PRODUCT', subject_id=product, status='UNKNOWN', review_ids=[], eligible_review_count=0)


def test_database_timezone_day_and_python_as_of_are_separate_current_behavior(conn, seeded_tenant_product_and_competitor):
    """Fixed boundary instant: SQL timezone determines the date sent to Python.

    Eligibility remains SQL CURRENT_TIMESTAMP even when as_of is far ahead.
    No assertion depends on the host's calendar date.
    """
    tenant, product, _ = seeded_tenant_product_and_competitor
    old = _insert_scored_review(conn, tenant, 'PRODUCT', 'positive', .9, .05, product_id=product)
    future = _insert_scored_review(conn, tenant, 'PRODUCT', 'negative', .05, .9, product_id=product)
    with conn.cursor() as q:
        q.execute("UPDATE reviews SET review_date='2020-01-01 23:30:00+00' WHERE review_id=%s", (old,))
        q.execute("UPDATE reviews SET review_date=CURRENT_TIMESTAMP + INTERVAL '1 day' WHERE review_id=%s", (future,))
    conn.commit()
    weights = []
    for zone, expected_date in [('Pacific/Kiritimati', date(2020, 1, 2)), ('Pacific/Honolulu', date(2020, 1, 1))]:
        with conn.cursor() as q:
            q.execute("SELECT set_config('TimeZone', %s, true)", (zone,))
        reviews = data_access.load_scored_reviews(conn, tenant, 'PRODUCT', product)
        assert [r['review_id'] for r in reviews] == [old]
        assert reviews[0]['effective_date'] == expected_date
        result = pipeline.get_subject_mpi(conn, tenant, 'PRODUCT', product, as_of=date(2020, 1, 2))
        weights.append(result['avg_recency_weight'])
    assert weights == [1., round(.5 ** (1 / scoring.RECENCY_HALF_LIFE_DAYS), 4)]
    result = pipeline.get_subject_mpi(conn, tenant, 'PRODUCT', product, as_of=date(9999, 1, 1))
    assert result['review_count'] == 1

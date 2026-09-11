"""
Integration tests for rag/structured_summaries.py against a real
PostgreSQL instance. The narrative-generator tests below only need
AI_TEST_DATABASE_URL (pure SQL, no MinIO/embedding model involved); the
upsert/full-regenerate tests additionally need AI_TEST_MINIO_ENDPOINT
(and AI_TEST_EMBEDDINGS for the one test that runs a real ingest), same
gating convention as test_rag_integration.py.
"""
import io
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

from src.ai.rag import structured_summaries

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
MINIO_ENDPOINT = os.getenv("AI_TEST_MINIO_ENDPOINT")
MINIO_ACCESS_KEY = os.getenv("AI_TEST_MINIO_ACCESS_KEY", "minio_admin")
MINIO_SECRET_KEY = os.getenv("AI_TEST_MINIO_SECRET_KEY", "local_test_password_only")
TEST_BUCKET = "ceopro-rag-knowledge-test"

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")

_needs_minio = pytest.mark.skipif(not MINIO_ENDPOINT, reason="AI_TEST_MINIO_ENDPOINT not set")
_needs_embeddings = pytest.mark.skipif(not os.getenv("AI_TEST_EMBEDDINGS"), reason="AI_TEST_EMBEDDINGS not set - downloads a real model")


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


@pytest.fixture
def minio_client():
    from minio import Minio
    client = Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=False)
    if not client.bucket_exists(TEST_BUCKET):
        client.make_bucket(TEST_BUCKET)
    yield client


def _insert_company(conn, country_code="JO") -> str:
    tenant_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, %s, %s, 'JOD');",
            (tenant_id, f"Test Co {tenant_id[:8]}", country_code),
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


def _insert_invoice_with_item(conn, tenant_id, product_id, quantity, unit_price, issue_date=None):
    invoice_id = str(uuid.uuid4())
    issue_date = issue_date or datetime.now(timezone.utc)
    total = quantity * unit_price
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO invoices (invoice_id, tenant_id, invoice_number, issue_date, subtotal, total_amount, currency) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'JOD');",
            (invoice_id, tenant_id, f"INV-{invoice_id[:8]}", issue_date, total, total),
        )
        cursor.execute(
            "INSERT INTO invoice_items (tenant_id, invoice_id, product_id, quantity, unit_price, total_price) "
            "VALUES (%s, %s, %s, %s, %s, %s);",
            (tenant_id, invoice_id, product_id, quantity, unit_price, total),
        )
    return invoice_id


def _insert_competitor(conn, tenant_id, name, tier="STRATEGIC", scope="BROAD_DOMAIN", match_rate=0.6, distance_km=None, city=None) -> str:
    competitor_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO global_competitors (global_competitor_id, competitor_name, visibility, added_by_tenant_id, is_manufacturer, city) "
            "VALUES (%s, %s, 'PRIVATE', %s, FALSE, %s);",
            (competitor_id, name, tenant_id, city),
        )
        cursor.execute(
            "INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked, tier, competitor_scope, product_match_rate, distance_km) "
            "VALUES (%s, %s, TRUE, %s, %s, %s, %s);",
            (tenant_id, competitor_id, tier, scope, match_rate, distance_km),
        )
    return competitor_id


def _insert_business_review_with_sentiment(conn, tenant_id, score, label="POSITIVE"):
    review_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO reviews (review_id, tenant_id, subject_type, source_platform, review_text) "
            "VALUES (%s, %s, 'BUSINESS', 'GOOGLE', 'Great service overall.');",
            (review_id, tenant_id),
        )
    from src.ai.sentiment.evidence import insert_sentiment_result
    insert_sentiment_result(conn, review_id, tenant_id, label, max(score, 0) + 0.1, 0.1, max(-score, 0) + 0.1, 0.9, "test-model-v1")


def _insert_competitor_review_with_sentiment(conn, tenant_id, competitor_id, score, label="NEGATIVE"):
    review_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO reviews (review_id, tenant_id, subject_type, competitor_id, source_platform, review_text) "
            "VALUES (%s, %s, 'COMPETITOR', %s, 'FACEBOOK', 'Shipping was slow.');",
            (review_id, tenant_id, competitor_id),
        )
    from src.ai.sentiment.evidence import insert_sentiment_result
    insert_sentiment_result(conn, review_id, tenant_id, label, max(score, 0) + 0.1, 0.1, max(-score, 0) + 0.1, 0.9, "test-model-v1")


def _insert_competitor_price(conn, tenant_id, product_id, competitor_id, scraped_price):
    source_id = str(uuid.uuid4())
    mapping_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
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
            (tenant_id, mapping_id, scraped_price),
        )


def test_sales_history_summary_reflects_real_invoice_data(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Espresso Machine")
    _insert_invoice_with_item(conn, tenant_id, product_id, quantity=3, unit_price=100.0)
    conn.commit()

    summary = structured_summaries.generate_sales_history_summary(conn, tenant_id)
    assert "Espresso Machine" in summary
    assert "3 units sold" in summary
    assert "300.00 revenue" in summary


def test_sales_history_summary_excludes_invoices_outside_the_window(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Old Product")
    old_date = datetime.now(timezone.utc) - timedelta(days=200)
    _insert_invoice_with_item(conn, tenant_id, product_id, quantity=5, unit_price=20.0, issue_date=old_date)
    conn.commit()

    summary = structured_summaries.generate_sales_history_summary(conn, tenant_id, window_days=90)
    assert "Old Product" not in summary
    assert "0 invoices" in summary


def test_sales_history_summary_handles_no_sales_honestly(conn):
    tenant_id = _insert_company(conn)
    conn.commit()
    summary = structured_summaries.generate_sales_history_summary(conn, tenant_id)
    assert "0 invoices" in summary
    assert "No invoice line items" in summary


def test_competitor_landscape_summary_lists_real_confirmed_competitors(conn):
    tenant_id = _insert_company(conn)
    _insert_competitor(conn, tenant_id, "Rival Electronics", tier="STRATEGIC", scope="BROAD_DOMAIN", match_rate=0.75, distance_km=3.2, city="Amman")
    conn.commit()

    summary = structured_summaries.generate_competitor_landscape_summary(conn, tenant_id)
    assert "Rival Electronics" in summary
    assert "STRATEGIC" in summary
    assert "75%" in summary
    assert "3.2km" in summary
    assert "Amman" in summary


def test_competitor_landscape_summary_handles_no_competitors_honestly(conn):
    tenant_id = _insert_company(conn)
    conn.commit()
    summary = structured_summaries.generate_competitor_landscape_summary(conn, tenant_id)
    assert "no confirmed, tracked competitors yet" in summary


def test_sentiment_trends_summary_includes_business_and_competitor_scores(conn):
    tenant_id = _insert_company(conn)
    competitor_id = _insert_competitor(conn, tenant_id, "Rival Co")
    conn.commit()
    _insert_business_review_with_sentiment(conn, tenant_id, score=0.5, label="POSITIVE")
    _insert_competitor_review_with_sentiment(conn, tenant_id, competitor_id, score=-0.6, label="NEGATIVE")
    conn.commit()

    summary = structured_summaries.generate_sentiment_trends_summary(conn, tenant_id)
    assert "Overall business sentiment" in summary
    assert "Rival Co" in summary


def test_market_pricing_summary_reflects_real_price_gap(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget", current_price=50.0)
    competitor_id = _insert_competitor(conn, tenant_id, "Cheaper Co")
    conn.commit()
    _insert_competitor_price(conn, tenant_id, product_id, competitor_id, scraped_price=40.0)
    conn.commit()

    summary = structured_summaries.generate_market_pricing_summary(conn, tenant_id)
    assert "Widget" in summary
    assert "50.00 JOD" in summary
    assert "40.00 JOD" in summary
    assert "higher" in summary


def test_market_pricing_summary_handles_no_observations_honestly(conn):
    tenant_id = _insert_company(conn)
    conn.commit()
    summary = structured_summaries.generate_market_pricing_summary(conn, tenant_id)
    assert "no real competitor price observations yet" in summary


@_needs_minio
def test_upsert_summary_document_creates_then_updates_the_same_slot(conn, minio_client):
    tenant_id = _insert_company(conn)
    conn.commit()

    doc_id_1 = structured_summaries._upsert_summary_document(
        conn, minio_client, tenant_id, structured_summaries.SLOT_SALES_HISTORY, "First version.", TEST_BUCKET,
    )
    doc_id_2 = structured_summaries._upsert_summary_document(
        conn, minio_client, tenant_id, structured_summaries.SLOT_SALES_HISTORY, "Second version.", TEST_BUCKET,
    )
    assert doc_id_1 == doc_id_2  # same slot, same document row - never a duplicate

    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM rag_documents_metadata WHERE tenant_id = %s;", (tenant_id,))
        assert cursor.fetchone()[0] == 1
        cursor.execute("SELECT processed_status FROM rag_documents_metadata WHERE document_id = %s;", (doc_id_1,))
        assert cursor.fetchone()[0] == "Pending"  # regeneration re-arms ingestion

    text = minio_client.get_object(TEST_BUCKET, structured_summaries._object_key(structured_summaries.SLOT_SALES_HISTORY)).read()
    assert text.decode("utf-8") == "Second version."


@_needs_minio
@_needs_embeddings
def test_regenerate_all_structured_summaries_ingests_real_chunks(conn, minio_client):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Espresso Machine")
    _insert_invoice_with_item(conn, tenant_id, product_id, quantity=2, unit_price=75.0)
    conn.commit()

    result = structured_summaries.regenerate_all_structured_summaries(conn, minio_client, tenant_id, bucket=TEST_BUCKET)

    assert result["chunks_ingested_for"] == len(structured_summaries.ALL_SLOTS)
    assert all(doc_id is not None for doc_id in result["document_ids"].values())

    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM rag_document_chunks WHERE tenant_id = %s;", (tenant_id,))
        assert cursor.fetchone()[0] > 0  # real chunks, actually embedded and persisted

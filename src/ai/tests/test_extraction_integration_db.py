"""
Integration test for extraction/data_access.py, evidence.py, and pipeline.py
against a real PostgreSQL instance running the actual init_schema.sql +
migrations/ (news_record/social_mention/extracted_entity and their
extraction_status columns are migration-only, not in init_schema.sql - apply
via src/infrastructure/database/run_migrations.py, not just init_schema.sql
alone). Same convention as the other *_integration_db.py files: skipped
unless AI_TEST_DATABASE_URL is set.
"""

import os
import uuid

import psycopg2
import pytest

from src.ai.extraction import data_access, evidence, pipeline
from src.ai.extraction.regex_patterns import ExtractedEntity

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
def seeded_tenant(conn):
    tenant_id = str(uuid.uuid4())
    product_id = str(uuid.uuid4())
    competitor_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO companies (tenant_id, business_name, country_code, primary_currency)
            VALUES (%s, 'Extraction Test Co', 'JO', 'JOD');
            """,
            (tenant_id,),
        )
        cursor.execute(
            """
            INSERT INTO products (product_id, tenant_id, product_name, current_price, currency)
            VALUES (%s, %s, 'Sunscreen SPF 50', 18.00, 'JOD');
            """,
            (product_id, tenant_id),
        )
        cursor.execute(
            """
            INSERT INTO competitors (competitor_id, tenant_id, competitor_name, country_code)
            VALUES (%s, %s, 'Rival Pharmacy', 'JO');
            """,
            (competitor_id, tenant_id),
        )
    conn.commit()
    return tenant_id, product_id, competitor_id


def test_load_known_product_names(conn, seeded_tenant):
    tenant_id, _, _ = seeded_tenant
    names = data_access.load_known_product_names(conn, tenant_id)
    assert names == ["Sunscreen SPF 50"]


def test_load_known_competitor_names(conn, seeded_tenant):
    tenant_id, _, _ = seeded_tenant
    names = data_access.load_known_competitor_names(conn, tenant_id)
    assert names == ["Rival Pharmacy"]


def test_load_known_product_names_excludes_soft_deleted(conn, seeded_tenant):
    """products.deleted_at (added after this module was first built) must be respected."""
    tenant_id, product_id, _ = seeded_tenant
    with conn.cursor() as cursor:
        cursor.execute("UPDATE products SET deleted_at = NOW() WHERE product_id = %s;", (product_id,))
    conn.commit()

    assert data_access.load_known_product_names(conn, tenant_id) == []


def test_load_known_competitor_names_excludes_deactivated(conn, seeded_tenant):
    """competitors.is_active (added after this module was first built) must be respected."""
    tenant_id, _, competitor_id = seeded_tenant
    with conn.cursor() as cursor:
        cursor.execute("UPDATE competitors SET is_active = FALSE WHERE competitor_id = %s;", (competitor_id,))
    conn.commit()

    assert data_access.load_known_competitor_names(conn, tenant_id) == []


def test_load_known_names_empty_for_tenant_with_no_products(conn):
    other_tenant_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO companies (tenant_id, business_name, country_code, primary_currency)
            VALUES (%s, 'Empty Catalog Co', 'JO', 'JOD');
            """,
            (other_tenant_id,),
        )
    conn.commit()
    assert data_access.load_known_product_names(conn, other_tenant_id) == []
    assert data_access.load_known_competitor_names(conn, other_tenant_id) == []


@pytest.fixture
def seeded_news_record(conn, seeded_tenant):
    tenant_id, _, _ = seeded_tenant
    news_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO news_record (news_id, tenant_id, source_url, headline, body_text)
            VALUES (%s, %s, %s, %s, %s);
            """,
            (
                news_id, tenant_id, "https://example.com/a", "Headline",
                "Sunscreen SPF 50 now 20% off, contact info@example.com",
            ),
        )
    conn.commit()
    return news_id


@pytest.fixture
def seeded_social_mention(conn, seeded_tenant):
    tenant_id, _, _ = seeded_tenant
    mention_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO social_mention (mention_id, tenant_id, platform, mention_text)
            VALUES (%s, %s, 'twitter', 'Rival Pharmacy is selling it for JOD 15');
            """,
            (mention_id, tenant_id),
        )
    conn.commit()
    return mention_id


def test_load_pending_news_records_reads_seeded_row(conn, seeded_tenant, seeded_news_record):
    tenant_id, _, _ = seeded_tenant
    pending = data_access.load_pending_news_records(conn, tenant_id)
    assert len(pending) == 1
    assert pending[0]["news_id"] == seeded_news_record
    assert "Sunscreen" in pending[0]["body_text"]


def test_load_pending_news_records_excludes_already_processed(conn, seeded_tenant, seeded_news_record):
    tenant_id, _, _ = seeded_tenant
    data_access.mark_news_record_status(conn, seeded_news_record, "Processed")
    conn.commit()

    assert data_access.load_pending_news_records(conn, tenant_id) == []


def test_load_pending_social_mentions_reads_seeded_row(conn, seeded_tenant, seeded_social_mention):
    tenant_id, _, _ = seeded_tenant
    pending = data_access.load_pending_social_mentions(conn, tenant_id)
    assert len(pending) == 1
    assert pending[0]["mention_id"] == seeded_social_mention
    assert "Rival Pharmacy" in pending[0]["mention_text"]


def test_insert_extracted_entities_writes_rows_with_correct_source(conn, seeded_tenant, seeded_news_record):
    tenant_id, _, _ = seeded_tenant
    entities = [
        ExtractedEntity(entity_type="EMAIL", text="info@example.com", start=0, end=16),
        ExtractedEntity(
            entity_type="PRODUCT", text="sunscreen", start=20, end=29,
            normalized_value="Sunscreen SPF 50", confidence=0.95,
        ),
    ]

    entity_ids = evidence.insert_extracted_entities(conn, tenant_id, "news_record", seeded_news_record, entities)
    conn.commit()

    assert len(entity_ids) == 2
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT entity_type, entity_value, confidence_score, source_table, source_record_id "
            "FROM extracted_entity WHERE tenant_id = %s ORDER BY entity_type;",
            (tenant_id,),
        )
        rows = cursor.fetchall()

    assert rows[0][0] == "EMAIL"
    assert rows[0][1] == "info@example.com"
    assert rows[0][2] is None
    assert rows[1][0] == "PRODUCT"
    assert rows[1][1] == "Sunscreen SPF 50"  # normalized_value, not raw text
    assert float(rows[1][2]) == 0.95
    assert rows[1][3] == "news_record"
    assert str(rows[1][4]) == seeded_news_record


def test_extract_and_store_news_records_end_to_end_against_real_db(conn, seeded_tenant, seeded_news_record):
    tenant_id, _, _ = seeded_tenant

    processed_count = pipeline.extract_and_store_news_records(conn, tenant_id)

    assert processed_count == 1
    with conn.cursor() as cursor:
        cursor.execute("SELECT extraction_status FROM news_record WHERE news_id = %s;", (seeded_news_record,))
        assert cursor.fetchone()[0] == "Processed"

        cursor.execute(
            "SELECT entity_type FROM extracted_entity WHERE source_table = 'news_record' AND source_record_id = %s;",
            (seeded_news_record,),
        )
        entity_types = {row[0] for row in cursor.fetchall()}
    # Real regex extraction against the seeded body_text: DISCOUNT ("20% off") and EMAIL are pattern-shaped;
    # PRODUCT depends on catalog matching against the tenant's own "Sunscreen SPF 50" product.
    assert "EMAIL" in entity_types
    assert "DISCOUNT" in entity_types
    assert "PRODUCT" in entity_types

    # A second run must not reprocess the now-Processed row.
    second_run_count = pipeline.extract_and_store_news_records(conn, tenant_id)
    assert second_run_count == 0


def test_extract_and_store_social_mentions_end_to_end_against_real_db(conn, seeded_tenant, seeded_social_mention):
    tenant_id, _, _ = seeded_tenant

    processed_count = pipeline.extract_and_store_social_mentions(conn, tenant_id)

    assert processed_count == 1
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT extraction_status FROM social_mention WHERE mention_id = %s;", (seeded_social_mention,)
        )
        assert cursor.fetchone()[0] == "Processed"

        cursor.execute(
            "SELECT entity_type, entity_value FROM extracted_entity "
            "WHERE source_table = 'social_mention' AND source_record_id = %s;",
            (seeded_social_mention,),
        )
        rows = cursor.fetchall()
    entity_types = {row[0] for row in rows}
    assert "MONEY" in entity_types  # "JOD 15"
    assert "COMPETITOR" in entity_types  # "Rival Pharmacy", the seeded tenant's known competitor

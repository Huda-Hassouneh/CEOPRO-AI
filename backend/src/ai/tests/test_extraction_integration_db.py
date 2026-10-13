"""
Integration test for extraction/data_access.py against a real PostgreSQL
instance running the actual Final_schema.sql (+ migrations/). Same
convention as the other *_integration_db.py files: skipped unless
AI_TEST_DATABASE_URL is set.
"""

import json
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
    global_competitor_id = str(uuid.uuid4())
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
            VALUES (%s, %s, %s, 18.00, 'JOD');
            """,
            (product_id, tenant_id, json.dumps({"en": "Sunscreen SPF 50", "ar": "واقي شمس"})),
        )
        cursor.execute(
            """
            INSERT INTO global_competitors (global_competitor_id, competitor_name, visibility, added_by_tenant_id)
            VALUES (%s, 'Rival Pharmacy', 'PRIVATE', %s);
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


def test_load_known_product_names(conn, seeded_tenant):
    tenant_id, _, _ = seeded_tenant
    names = data_access.load_known_product_names(conn, tenant_id)
    assert sorted(names) == ["Sunscreen SPF 50", "واقي شمس"]


def test_load_known_competitor_names(conn, seeded_tenant):
    tenant_id, _, _ = seeded_tenant
    names = data_access.load_known_competitor_names(conn, tenant_id)
    assert names == ["Rival Pharmacy"]


def test_load_known_product_names_excludes_soft_deleted(conn, seeded_tenant):
    """products.deleted_at must be respected."""
    tenant_id, product_id, _ = seeded_tenant
    with conn.cursor() as cursor:
        cursor.execute("UPDATE products SET deleted_at = NOW() WHERE product_id = %s;", (product_id,))
    conn.commit()

    assert data_access.load_known_product_names(conn, tenant_id) == []


def test_load_known_competitor_names_excludes_untracked(conn, seeded_tenant):
    """tenant_competitors.is_tracked must be respected."""
    tenant_id, _, global_competitor_id = seeded_tenant
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE tenant_competitors SET is_tracked = FALSE WHERE tenant_id = %s AND global_competitor_id = %s;",
            (tenant_id, global_competitor_id),
        )
    conn.commit()

    assert data_access.load_known_competitor_names(conn, tenant_id) == []


def test_load_known_competitor_names_excludes_other_tenants_private_competitors(conn, seeded_tenant):
    """A PRIVATE competitor another tenant added, and never tracked by this one, must not leak in."""
    tenant_id, _, _ = seeded_tenant
    other_tenant_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, 'Other Co', 'JO', 'JOD');",
            (other_tenant_id,),
        )
        cursor.execute(
            "INSERT INTO global_competitors (competitor_name, visibility, added_by_tenant_id) "
            "VALUES ('Other Tenant Only Competitor', 'PRIVATE', %s);",
            (other_tenant_id,),
        )
    conn.commit()

    assert data_access.load_known_competitor_names(conn, tenant_id) == ["Rival Pharmacy"]


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


class _FakeRedis:
    """Minimal in-memory stand-in for catalog_cache.get_known_names()'s redis_client
    dependency - a real Redis server isn't needed to verify catalog matching
    actually resolves through the full pipeline; only .get()/.set() are used."""

    def __init__(self):
        self._store = {}

    def get(self, key):
        return self._store.get(key)

    def set(self, key, value, ex=None):
        self._store[key] = value


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

    processed_count = pipeline.extract_and_store_news_records(conn, tenant_id, redis_client=_FakeRedis())

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
    # PRODUCT depends on catalog matching (via the fake in-memory Redis cache) against the tenant's own product.
    assert "EMAIL" in entity_types
    assert "DISCOUNT" in entity_types
    assert "PRODUCT" in entity_types

    # A second run must not reprocess the now-Processed row.
    second_run_count = pipeline.extract_and_store_news_records(conn, tenant_id, redis_client=_FakeRedis())
    assert second_run_count == 0


def test_extract_and_store_social_mentions_end_to_end_against_real_db(conn, seeded_tenant, seeded_social_mention):
    tenant_id, _, _ = seeded_tenant

    processed_count = pipeline.extract_and_store_social_mentions(conn, tenant_id, redis_client=_FakeRedis())

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


def test_a_record_whose_entity_value_is_rejected_by_the_db_does_not_poison_the_rest_of_the_batch(
    conn, seeded_tenant
):
    """
    extracted_entity.entity_value is VARCHAR(512). A catalog match on a product
    name longer than that (a real possibility - long product/competitor names)
    fails the INSERT at the database level, which aborts the transaction. Before
    pipeline.py wrapped each record's DB work in a SAVEPOINT, this poisoned the
    connection: the except block's own "mark this record Failed" recovery write
    then also failed, an uncaught exception that crashed the whole function and
    left every other record in the batch - including perfectly valid ones -
    stuck at 'Pending' forever. Reproduced directly before the fix.
    """
    tenant_id, _, _ = seeded_tenant
    long_name = "A" + "b" * 520  # 521 chars, over the VARCHAR(512) limit

    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE products SET product_name = %s WHERE tenant_id = %s;",
            (json.dumps({"en": long_name}), tenant_id),
        )
        bad_news_id = str(uuid.uuid4())
        good_news_id = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO news_record (news_id, tenant_id, source_url, headline, body_text) "
            "VALUES (%s, %s, 'https://example.com/a', 'h', %s);",
            (bad_news_id, tenant_id, long_name),
        )
        cursor.execute(
            "INSERT INTO news_record (news_id, tenant_id, source_url, headline, body_text) "
            "VALUES (%s, %s, 'https://example.com/b', 'h', 'A perfectly normal news body, nothing wrong here.');",
            (good_news_id, tenant_id),
        )
    conn.commit()

    processed_count = pipeline.extract_and_store_news_records(conn, tenant_id, redis_client=_FakeRedis())

    assert processed_count == 1  # only the good record counts as processed
    with conn.cursor() as cursor:
        cursor.execute("SELECT news_id, extraction_status FROM news_record WHERE tenant_id = %s;", (tenant_id,))
        statuses = dict(cursor.fetchall())
    assert statuses[bad_news_id] == "Failed"
    assert statuses[good_news_id] == "Processed"  # must not be left stranded at 'Pending' by a crash


def test_extract_and_store_news_records_without_redis_client_still_runs_regex_tier(
    conn, seeded_tenant, seeded_news_record
):
    """redis_client is optional - omitting it must not error, just skip catalog matching (extractor.py's own contract)."""
    tenant_id, _, _ = seeded_tenant

    processed_count = pipeline.extract_and_store_news_records(conn, tenant_id)

    assert processed_count == 1
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT entity_type FROM extracted_entity WHERE source_table = 'news_record' AND source_record_id = %s;",
            (seeded_news_record,),
        )
        entity_types = {row[0] for row in cursor.fetchall()}
    assert "EMAIL" in entity_types
    assert "PRODUCT" not in entity_types  # no redis_client -> no catalog matching

"""
Live-DB test for src/infrastructure/database/run_migrations.py
(PENDING_ACTIONS.md #22). Same convention as the *_integration_db.py files:
skipped unless AI_TEST_DATABASE_URL is set. This script's entire purpose is
DB interaction, so there's no meaningful offline unit test for it - point it
at a genuinely empty disposable database (not one already running other
tests' data), since it applies the real init_schema.sql.

Requires a superuser-equivalent role (the migrations themselves need
CREATE ROLE/CREATE EXTENSION privileges) - the same AI_TEST_DATABASE_URL
this whole suite already runs as for every other *_integration_db.py file.
"""

import os

import psycopg2
import pytest

from src.infrastructure.database import run_migrations

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test"
)


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.close()


def test_run_applies_base_schema_and_all_migrations_on_a_fresh_database(conn):
    applied = run_migrations.run(conn)

    assert "20260807225947_add_campaigns_table.sql" in applied
    assert "20260808020000_add_app_role_and_force_rls.sql" in applied

    with conn.cursor() as cursor:
        cursor.execute("SELECT to_regclass('public.companies');")
        assert cursor.fetchone()[0] == "companies"
        cursor.execute("SELECT to_regclass('public.campaigns');")
        assert cursor.fetchone()[0] == "campaigns"
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'model_versions';")
        columns = {row[0] for row in cursor.fetchall()}
        assert "artifact_path" in columns
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'products';")
        columns = {row[0] for row in cursor.fetchall()}
        assert "cost" in columns


def test_run_is_idempotent_on_a_second_call(conn):
    # Tests in this file share one live database (no per-test reset), so an
    # earlier test may have already applied everything - this test only
    # asserts the idempotency property itself, not that there was pending
    # work to do.
    run_migrations.run(conn)

    second_run = run_migrations.run(conn)
    assert second_run == []  # everything already applied, nothing to do


def test_run_skips_init_schema_when_base_schema_already_present(conn):
    run_migrations.run(conn)  # first call creates the base schema

    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM companies;")
        count_before = cursor.fetchone()[0]

    run_migrations.run(conn)  # must not try to re-run init_schema.sql (which would error - no IF NOT EXISTS)

    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM companies;")
        count_after = cursor.fetchone()[0]

    assert count_before == count_after

"""
Integration test for search_quota.py against a real PostgreSQL instance.
Skipped unless AI_TEST_DATABASE_URL is set, same convention as every
other *_integration_db.py test in this package.
"""
import os

import psycopg2
import pytest

from src.market_scraper.search_quota import has_budget, queries_used_today, record_query

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


def test_no_usage_yet_has_full_budget(conn):
    assert queries_used_today(conn) == 0
    assert has_budget(conn, daily_limit=100) is True


def test_recording_a_query_increments_todays_count(conn):
    # No conn.commit() here on purpose: each test gets its own fresh
    # connection/transaction from the fixture, and Postgres already
    # makes a transaction see its own uncommitted writes - committing
    # would let usage_date rows (keyed on today's real date, shared by
    # every test in this file) leak between tests and even between
    # separate runs on the same day, since query_count accumulates via
    # ON CONFLICT DO UPDATE rather than simply overwriting.
    record_query(conn)
    record_query(conn)
    assert queries_used_today(conn) == 2


def test_record_query_accepts_a_count_greater_than_one(conn):
    record_query(conn, count=5)
    assert queries_used_today(conn) == 5


def test_has_budget_becomes_false_once_the_limit_is_reached(conn):
    record_query(conn, count=100)
    assert has_budget(conn, daily_limit=100) is False


def test_has_budget_true_one_query_under_the_limit(conn):
    record_query(conn, count=99)
    assert has_budget(conn, daily_limit=100) is True

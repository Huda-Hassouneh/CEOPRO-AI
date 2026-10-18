"""
Integration test for search_cache.py against a real PostgreSQL instance.
Same convention as the other *_integration_db.py tests: skipped unless
AI_TEST_DATABASE_URL is set.
"""
import os

import psycopg2
import pytest

from src.market_scraper.discovery import CandidateSource
from src.market_scraper.search_cache import build_cache_key, get_cached, set_cached

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


def test_miss_returns_none(conn):
    assert get_cached(conn, "google_cse:some query that was never cached") is None


def test_set_then_get_round_trips_real_candidate_sources(conn):
    key = build_cache_key("google_cse", '"Espresso Machine" buy shop store price')
    candidates = [
        CandidateSource("Espresso Machine", "https://acme.example/espresso", "Buy Espresso - Acme"),
        CandidateSource("Espresso Machine", "https://beanco.example/espresso", "Espresso | Bean Co"),
    ]
    set_cached(conn, key, candidates)
    conn.commit()

    result = get_cached(conn, key)
    assert result == candidates


def test_set_overwrites_a_previous_entry_for_the_same_key(conn):
    key = build_cache_key("google_cse", "some query")
    set_cached(conn, key, [CandidateSource("X", "https://old.example/x", "Old")])
    conn.commit()
    set_cached(conn, key, [CandidateSource("X", "https://new.example/x", "New")])
    conn.commit()

    result = get_cached(conn, key)
    assert len(result) == 1
    assert result[0].url == "https://new.example/x"


def test_expired_entry_is_treated_as_a_miss(conn):
    key = build_cache_key("google_cse", "expiring query")
    set_cached(conn, key, [CandidateSource("X", "https://example.test/x", "X")], ttl_seconds=-1)
    conn.commit()

    assert get_cached(conn, key) is None


def test_different_sources_for_the_same_query_text_are_independent_cache_entries(conn):
    google_key = build_cache_key("google_cse", "same text")
    searxng_key = build_cache_key("searxng", "same text")
    set_cached(conn, google_key, [CandidateSource("X", "https://google-result.example", "G")])
    conn.commit()

    assert get_cached(conn, searxng_key) is None
    assert get_cached(conn, google_key) is not None
